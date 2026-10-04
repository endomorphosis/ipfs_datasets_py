"""Resource lifecycle regressions, including an installed native TLC model.

Native tests never install a JVM/JAR. Their private launcher explicitly sizes
the JVM heap; legacy installer launchers with unconstrained JVM ergonomics are
outside this execution-only contract.
"""

from __future__ import annotations

import os
import shlex
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process as process_module
from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner, CancellationToken, RawProcessResult,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.tla import runners
from ipfs_datasets_py.logic.backends.tla.compiler import GeneratedTLAArtifacts, TLACompileBounds
from ipfs_datasets_py.logic.backends.tla.runners import (
    ApalacheBackend, ModelCheckOutcomeStatus, TLCBackend,
)
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind


SUCCESS = "Model checking completed. No error has been found.\n"


def _artifacts() -> GeneratedTLAArtifacts:
    return GeneratedTLAArtifacts(
        module_name="BoundedCounter",
        model_text=(
            "---- MODULE BoundedCounter ----\nEXTENDS Integers\nVARIABLE n\n"
            "Init == n = 0\nNext == n < 3 /\\ n' = n + 1\n"
            "Spec == Init /\\ [][Next]_n\nSafety == n \\in 0..3\n====\n"
        ),
        tlc_config_text="SPECIFICATION Spec\nINVARIANT Safety\nCHECK_DEADLOCK FALSE\n",
        apalache_config_text="INIT Init\nNEXT Next\nINVARIANT Safety\n",
        source_map=(), losses=(), bounds=TLACompileBounds(max_steps=4),
        source_document_id="test:bounded-counter", source_kind="state_transition",
        safety_properties=("Safety",), liveness_properties=(), fairness_limitations=(),
    )


def _request(**bounds) -> BackendRequest:
    return BackendRequest(
        request_id="request:tlc:resource", claim_id="claim:counter",
        declaration_id="declaration:counter", claim_digest="1" * 64,
        obligation_id="obligation:counter", obligation_digest="2" * 64,
        assumption_ids=(),
        logic_family="state_transition", query_kind=QueryKind.SATISFIABILITY,
        bounds=ExecutionBounds(**bounds),
    )


def _backend(execute, *, backend_type=TLCBackend, **kwargs):
    return backend_type(
        runner=BoundedToolRunner(executor=execute), executable="/trusted/checker",
        jvm_probe=lambda: True, lazy_install=False, **kwargs,
    )


@pytest.mark.parametrize("backend_type", [TLCBackend, ApalacheBackend])
def test_model_and_version_share_remaining_budget_memory_and_signal(monkeypatch, backend_type):
    clock = [100.0]
    monkeypatch.setattr(runners, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    token = CancellationToken()
    invocations = []

    def execute(invocation, cancellation):
        assert cancellation is token
        invocations.append(invocation)
        clock[0] += 0.25
        return RawProcessResult(returncode=0, stdout=SUCCESS + "Checker reports no error\n")

    request = _request(timeout_ms=1000, max_memory_bytes=128 * 1024**2, max_output_bytes=8192)
    outcome = _backend(execute, backend_type=backend_type).check(
        _artifacts(), request=request, cancellation=token,
    )
    assert outcome.result.status is ResultStatus.SATISFIED
    assert outcome.receipt.elapsed_ms == 500
    assert outcome.result.usage.elapsed_ms == 500
    assert len(invocations) == 2
    assert invocations[0].limits.timeout_seconds == 1
    assert invocations[1].limits.timeout_seconds == 0.75
    for invocation in invocations:
        limits = invocation.limits
        assert limits.cpu_seconds == limits.timeout_seconds
        assert limits.resident_memory_bytes == request.bounds.max_memory_bytes
        assert limits.memory_bytes == 4 * 1024**3
        assert limits.max_output_bytes == 8192


def test_precancelled_request_never_discovers_or_installs(monkeypatch):
    token = CancellationToken()
    token.cancel()
    backend = _backend(lambda *_: pytest.fail("process launched after cancellation"))
    monkeypatch.setattr(backend, "_probe", lambda **_: pytest.fail("probe/install after cancellation"))
    outcome = backend.check(_artifacts(), cancellation=token)
    assert outcome.receipt.status is ModelCheckOutcomeStatus.ERROR
    assert "cancelled" in outcome.receipt.reason
    assert outcome.receipt.command == ()


@pytest.mark.parametrize("cancel", [True, False])
def test_discovery_exhaustion_prevents_native_launch(monkeypatch, cancel):
    clock = [100.0]
    monkeypatch.setattr(runners, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    token = CancellationToken()
    backend = _backend(lambda *_: pytest.fail("deadline/cancellation lost after discovery"))
    probe = backend._probe

    def slow_probe(**kwargs):
        if cancel:
            token.cancel()
        else:
            clock[0] += 1.1
        return probe(**kwargs)

    monkeypatch.setattr(backend, "_probe", slow_probe)
    outcome = backend.check(_artifacts(), request=_request(timeout_ms=1000), cancellation=token)
    expected = ModelCheckOutcomeStatus.ERROR if cancel else ModelCheckOutcomeStatus.TIMED_OUT
    assert outcome.receipt.status is expected
    assert outcome.receipt.command == ()


@pytest.mark.parametrize("field", ["cancelled", "timed_out", "resource_exhausted"])
def test_interrupted_model_does_not_launch_version(field):
    invocations = []

    def execute(invocation, _):
        invocations.append(invocation)
        return RawProcessResult(returncode=0, stdout=SUCCESS, **{field: True})

    outcome = _backend(execute).check(_artifacts())
    assert len(invocations) == 1
    assert outcome.result.status is not ResultStatus.SATISFIED
    assert outcome.receipt.tool_version == "unavailable"


@pytest.mark.parametrize("cancel", [True, False])
def test_version_consuming_request_deadline_or_cancellation_cannot_return_success(monkeypatch, cancel):
    clock = [100.0]
    monkeypatch.setattr(runners, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    token = CancellationToken()
    invocations = []

    def execute(invocation, cancellation):
        invocations.append(invocation)
        if len(invocations) == 2:
            if cancel:
                token.cancel()
            else:
                clock[0] += 1.1
        return RawProcessResult(returncode=0, stdout=SUCCESS)

    outcome = _backend(execute).check(_artifacts(), request=_request(timeout_ms=1000), cancellation=token)
    assert len(invocations) == 2
    assert outcome.receipt.status is (
        ModelCheckOutcomeStatus.ERROR if cancel else ModelCheckOutcomeStatus.TIMED_OUT
    )


@pytest.mark.parametrize("exhaustion", ["output", "workspace"])
def test_exhausted_output_or_workspace_cannot_establish_success(exhaustion):
    def execute(invocation, _):
        if exhaustion == "workspace":
            # Sparse file exercises the real runner's workspace accounting
            # without allocating the claimed storage in the test process.
            with (invocation.cwd / "oversized").open("wb") as stream:
                stream.truncate(invocation.limits.max_workspace_bytes + 1)
        return RawProcessResult(returncode=0, stdout=SUCCESS, output_truncated=exhaustion == "output")

    outcome = _backend(execute).check(_artifacts())
    assert outcome.receipt.status is ModelCheckOutcomeStatus.UNKNOWN
    assert outcome.result.status is not ResultStatus.SATISFIED


def test_input_budget_counts_model_and_configuration_together():
    artifacts = _artifacts()
    artifacts = replace(artifacts, model_text=artifacts.model_text + "\\* " + "x" * 5000 + "\n")
    calls = []

    def execute(invocation, _):
        calls.append(invocation)
        return RawProcessResult(returncode=0, stdout=SUCCESS)

    outcome = _backend(execute).check(artifacts)
    assert outcome.receipt.status is ModelCheckOutcomeStatus.PASSED
    assert calls[0].limits.max_input_bytes == len(artifacts.model_text.encode()) + len(artifacts.tlc_config_text.encode())


@pytest.fixture
def native_tlc_launcher(tmp_path):
    root = Path.home() / ".local/share/ipfs_datasets_py/theorem-provers"
    jar = Path(os.environ.get("IPFS_DATASETS_TEST_TLC_JAR", str(root / "tlc/1.8.0/tla2tools.jar")))
    java = Path(os.environ.get(
        "IPFS_DATASETS_TEST_TLC_JAVA",
        str(root / "Isabelle2025-2-linux-aarch64/Isabelle2025-2/contrib/jdk-21.0.9/arm64-linux/bin/java"),
    ))
    if not java.is_file() or not jar.is_file() or not Path("/proc/self/stat").is_file():
        pytest.skip("native TLC1.8/JVM11+ and Linux resource guards must already be installed")
    launcher = tmp_path / "tlc-memory-aware"
    args = [
        str(java), "-Xms16m", "-Xmx128m", "-XX:ActiveProcessorCount=1",
        "-XX:+UseSerialGC", "-XX:ReservedCodeCacheSize=64m",
        "-XX:CompressedClassSpaceSize=64m", "-cp", str(jar), "tlc2.TLC", "-workers", "1",
    ]
    launcher.write_text("#!/bin/sh\nexec " + shlex.join(args) + ' "$@"\n')
    launcher.chmod(0o700)
    return launcher


def test_installed_native_tlc_runs_small_counter_under_real_resource_bounds(native_tlc_launcher, tmp_path):
    observed = []

    def execute(invocation, cancellation):
        observed.append(invocation)
        return process_module.SubprocessExecutor().execute(invocation, cancellation)

    backend = TLCBackend(
        executable=str(native_tlc_launcher), jvm_probe=lambda: True, lazy_install=False,
        runner=BoundedToolRunner(executor=execute, workspace_root=tmp_path / "work"),
    )
    request = _request(timeout_ms=10000, max_memory_bytes=256 * 1024**2)
    outcome = backend.check(_artifacts(), request=request)
    assert outcome.receipt.status is ModelCheckOutcomeStatus.PASSED, outcome.receipt.to_dict()
    assert outcome.result.authority is ResultAuthority.MODEL_CHECK
    assert "4 distinct states found" in outcome.receipt.stdout
    assert "TLC" in outcome.receipt.tool_version
    assert "Version " in outcome.receipt.tool_version
    assert len(observed) == 2
    assert all(x.limits.resident_memory_bytes == request.bounds.max_memory_bytes for x in observed)
    assert all(x.limits.memory_bytes == 4 * 1024**3 for x in observed)
    assert not list((tmp_path / "work").iterdir())


@pytest.mark.parametrize("stop", ["deadline", "cancellation", "rss"])
def test_native_tlc_is_terminated_without_followup_probe(native_tlc_launcher, tmp_path, stop):
    token = CancellationToken()
    calls = []
    raw_results = []
    timer = None

    def execute(invocation, cancellation):
        nonlocal timer
        calls.append(invocation)
        if stop == "cancellation":
            timer = threading.Timer(0.2, token.cancel)
            timer.start()
        result = process_module.SubprocessExecutor().execute(invocation, cancellation)
        raw_results.append(result)
        return result

    backend = TLCBackend(
        executable=str(native_tlc_launcher), jvm_probe=lambda: True, lazy_install=False,
        runner=BoundedToolRunner(executor=execute, workspace_root=tmp_path / "work"),
    )
    artifacts = _artifacts()
    artifacts = replace(
        artifacts,
        model_text=artifacts.model_text.replace("n < 3", "n < 100000000").replace("0..3", "0..100000000"),
    )
    request = _request(
        timeout_ms=200 if stop == "deadline" else 5000,
        max_memory_bytes=(16 if stop == "rss" else 256) * 1024**2,
    )
    try:
        outcome = backend.check(artifacts, request=request, cancellation=token)
    finally:
        if timer is not None:
            timer.cancel()
            timer.join(timeout=1)
    assert len(calls) == len(raw_results) == 1, "interrupted model must not start a version JVM"
    assert raw_results[0].process_tree_terminated
    assert outcome.result.status is not ResultStatus.SATISFIED
    if stop == "deadline":
        assert raw_results[0].timed_out
        assert outcome.receipt.status is ModelCheckOutcomeStatus.TIMED_OUT
    elif stop == "cancellation":
        assert raw_results[0].cancelled
        assert outcome.receipt.status is ModelCheckOutcomeStatus.ERROR
    else:
        assert raw_results[0].resource_exhausted
        assert outcome.receipt.status is ModelCheckOutcomeStatus.UNKNOWN
    assert not list((tmp_path / "work").iterdir())
