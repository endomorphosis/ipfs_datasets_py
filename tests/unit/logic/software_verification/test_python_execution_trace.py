"""Hermetic Python execution tracing (SAWM-008).

Evidence subset:

* cold-import side-effect probe
* hermetic call / exception / async fixtures
* exact tree/source/environment/symbol binding
* payload bounds
* secret redaction
* test-only network denial
* cancellation emits no accepted transition
* private raw trace bodies never enter public records
* deterministic promised replay
"""

from __future__ import annotations

import json
import os
import socket
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    MAX_METADATA_BYTES,
    EventKind,
    PrivacyClass,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    IMPORT_DATABASE_OPENED,
    IMPORT_INSTALLER_INVOKED,
    IMPORT_MODEL_LOADED,
    IMPORT_NETWORK_PERFORMED,
    IMPORT_REPO_SCAN_PERFORMED,
    IMPORT_SOCKET_OPENED,
    IMPORT_SUBPROCESS_PERFORMED,
    IMPORT_WATCHER_STARTED,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    PYTHON_EXECUTION_TRACE_RECORD_INTERFACE,
    TRACE_CANCELLATION_INTERFACE,
    TRACE_COLLECTION_POLICY_INTERFACE,
    TRACE_REDACTOR_INTERFACE,
    PythonExecutionTraceError,
    PythonExecutionTracer,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceRedactor,
    TraceStatus,
    record_python_execution_trace,
    replay_deterministic_trace,
)


WORKSPACE_ROOT = Path(__file__).resolve().parents[5]


def _kinds(record: Any) -> set[str]:
    return {str(event.event_kind) for event in record.events}


def _call_fixture(value: int = 1) -> int:
    def pong() -> int:
        return value

    def ping() -> int:
        return pong()

    return ping()


def _exception_fixture() -> int:
    try:
        raise ValueError("bounded")
    except ValueError:
        return 2


async def _async_fixture() -> int:
    await _async_yield()
    return 3


async def _async_yield() -> None:
    return None


def _generator_fixture() -> list[int]:
    def inner():
        yield 1
        yield 2

    return list(inner())


def _secret_fixture() -> str:
    password = "test-only-password-value"  # noqa: F841
    api_key = "should-not-appear"  # noqa: F841
    return "ok"


def _bound_fixture() -> int:
    blob = "x" * 50_000  # noqa: F841
    return len(blob)


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
    assert TRACE_COLLECTION_POLICY_INTERFACE == "TraceCollectionPolicy@1"
    assert TRACE_REDACTOR_INTERFACE == "TraceRedactor@1"
    assert TRACE_CANCELLATION_INTERFACE == "TraceCancellation@1"
    assert PYTHON_EXECUTION_TRACE_RECORD_INTERFACE == "PythonExecutionTraceRecord@1"
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)
    assert PythonExecutionTracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE
    assert TraceCollectionPolicy.INTERFACE == TRACE_COLLECTION_POLICY_INTERFACE
    assert TraceRedactor.INTERFACE == TRACE_REDACTOR_INTERFACE
    assert TraceCancellation.INTERFACE == TRACE_CANCELLATION_INTERFACE


def test_import_hermeticity_flags_remain_false() -> None:
    assert IMPORT_NETWORK_PERFORMED is False
    assert IMPORT_SOCKET_OPENED is False
    assert IMPORT_INSTALLER_INVOKED is False
    assert IMPORT_SUBPROCESS_PERFORMED is False
    assert IMPORT_DATABASE_OPENED is False
    assert IMPORT_REPO_SCAN_PERFORMED is False
    assert IMPORT_WATCHER_STARTED is False
    assert IMPORT_MODEL_LOADED is False


def test_cold_import_side_effect_probe() -> None:
    script = textwrap.dedent(
        """
        import builtins
        import importlib
        import os
        import socket
        import sqlite3
        import subprocess
        import sys
        import threading

        def forbidden(operation):
            def fail(*args, **kwargs):
                raise AssertionError(f"{operation} during cold import: {args!r}")
            return fail

        socket.create_connection = forbidden("socket.create_connection")
        socket.getaddrinfo = forbidden("socket.getaddrinfo")
        _orig_socket = socket.socket
        class GuardedSocket(_orig_socket):
            def connect(self, *a, **k):
                raise AssertionError("socket.connect during cold import")
            def connect_ex(self, *a, **k):
                raise AssertionError("socket.connect_ex during cold import")
        socket.socket = GuardedSocket

        subprocess.Popen = forbidden("subprocess.Popen")
        subprocess.run = forbidden("subprocess.run")
        subprocess.call = forbidden("subprocess.call")
        subprocess.check_call = forbidden("subprocess.check_call")
        subprocess.check_output = forbidden("subprocess.check_output")
        os.system = forbidden("os.system")
        os.walk = forbidden("os.walk")
        os.scandir = forbidden("os.scandir")
        sqlite3.connect = forbidden("sqlite3.connect")
        threading.Thread.start = forbidden("threading.Thread.start")

        try:
            import pip
            pip.main = forbidden("pip.main")
        except Exception:
            pass

        banned = ("torch", "transformers", "watchdog")
        for name in list(sys.modules):
            if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
                del sys.modules[name]

        module = importlib.import_module(
            "ipfs_datasets_py.logic.software_verification.python_execution_trace"
        )
        assert module.IMPORT_NETWORK_PERFORMED is False
        assert module.IMPORT_SOCKET_OPENED is False
        assert module.IMPORT_INSTALLER_INVOKED is False
        assert module.IMPORT_SUBPROCESS_PERFORMED is False
        assert module.IMPORT_DATABASE_OPENED is False
        assert module.IMPORT_REPO_SCAN_PERFORMED is False
        assert module.IMPORT_WATCHER_STARTED is False
        assert module.IMPORT_MODEL_LOADED is False
        assert callable(module.record_python_execution_trace)
        assert callable(module.replay_deterministic_trace)
        for name in banned:
            assert name not in sys.modules, f"{name} loaded on cold import"
        _ = module.PythonExecutionTracer
        _ = module.TraceCollectionPolicy.hermetic()
        for name in banned:
            assert name not in sys.modules, f"{name} loaded on attribute access"
        print("ok")
        """
    )
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = "1"
    env["IPFS_DATASETS_AUTO_INSTALL"] = "0"
    env["IPFS_KIT_AUTO_INSTALL_DEPS"] = "0"
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(WORKSPACE_ROOT / "ipfs_datasets_py"),
            str(WORKSPACE_ROOT / "ipfs_kit_py"),
            str(WORKSPACE_ROOT),
            env.get("PYTHONPATH", ""),
        )
        if part
    )
    completed = __import__("subprocess").run(
        [sys.executable, "-c", script],
        cwd=str(WORKSPACE_ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ok" in completed.stdout


def test_call_fixture_records_call_and_return_with_exact_bindings() -> None:
    environment = {"language": "python", "python_major": "3", "python_minor": "12"}
    record = record_python_execution_trace(
        _call_fixture,
        4,
        environment_binding=environment,
        policy=TraceCollectionPolicy.hermetic(collect_lines=False),
    )
    kinds = _kinds(record)
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    assert record.cancelled is False
    assert record.accepted_transition_cid is None
    assert record.public_trace.language == "python"
    assert record.public_trace.environment_binding_cid == record.environment_binding_cid
    assert record.public_trace.tree_cid == record.tree_cid
    assert record.public_trace.source_cid == record.source_cid
    for event in record.events:
        assert event.tree_cid == record.tree_cid
        assert event.source_cid == record.source_cid
        assert event.environment_binding_cid == record.environment_binding_cid
        assert event.language == "python"
        assert "timestamp" not in event.to_dict()
        assert "wall_clock" not in event.to_dict()
        assert "hostname" not in event.to_dict()
        assert "pid" not in event.to_dict()
        assert event.logical_name
        assert event.code_cid
        assert event.line is None or event.line >= 0
    other = record_python_execution_trace(
        _call_fixture,
        4,
        environment_binding={"language": "python", "python_major": "3", "python_minor": "11"},
        policy=TraceCollectionPolicy.hermetic(collect_lines=False),
    )
    assert other.environment_binding_cid != record.environment_binding_cid
    assert record.events and other.events
    assert other.events[0].program_event_cid != record.events[0].program_event_cid


def test_exception_and_handler_fixture_preserves_raise_and_catch() -> None:
    record = record_python_execution_trace(
        _exception_fixture,
        policy=TraceCollectionPolicy.hermetic(collect_lines=True),
    )
    kinds = _kinds(record)
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    raised = next(event for event in record.events if event.event_kind == EventKind.RAISE.value)
    assert raised.exception_snapshot_cid is not None
    assert raised.stack_frame_cids
    caught = [event for event in record.events if event.event_kind in {EventKind.CATCH.value, EventKind.HANDLER.value}]
    assert caught
    assert any(event.handler_state_cid is not None for event in caught)


def test_async_and_yield_fixtures_record_await_or_yield() -> None:
    async_record = record_python_execution_trace(
        _async_fixture,
        policy=TraceCollectionPolicy.hermetic(collect_lines=False),
    )
    async_kinds = _kinds(async_record)
    assert EventKind.CALL.value in async_kinds
    assert EventKind.AWAIT.value in async_kinds or EventKind.RETURN.value in async_kinds
    gen_record = record_python_execution_trace(
        _generator_fixture,
        policy=TraceCollectionPolicy.hermetic(collect_lines=False),
    )
    gen_kinds = _kinds(gen_record)
    assert EventKind.YIELD.value in gen_kinds or EventKind.CALL.value in gen_kinds
    assert EventKind.RETURN.value in gen_kinds


def test_payload_bounds_are_enforced() -> None:
    record = record_python_execution_trace(
        _bound_fixture,
        policy=TraceCollectionPolicy.hermetic(
            collect_lines=False,
            max_payload_bytes=512,
            include_raw_bodies=True,
        ),
    )
    for event in record.events:
        encoded = canonical_dag_json_bytes(event.to_dict()["payload"])
        assert len(encoded) <= MAX_METADATA_BYTES
        assert len(encoded) <= 512 or event.payload.get("bounded") is True
    public = record.public_record()
    public_bytes = canonical_dag_json_bytes(
        {key: value for key, value in public.items() if key not in {"events", "public_trace", "observations", "policy", "redaction_profile"}}
    )
    assert len(public_bytes) <= MAX_METADATA_BYTES * 4
    for body in record.raw_bodies.values():
        encoded = canonical_dag_json_bytes(body)
        assert len(encoded) <= MAX_METADATA_BYTES


def test_secret_redaction_strips_credentials_from_records() -> None:
    redactor = TraceRedactor(TraceCollectionPolicy.hermetic())
    cleaned, redacted = redactor.redact_mapping(
        {
            "password": "test-only-password-value",
            "api_key": "should-not-appear",
            "x": 1,
        },
        budget=8,
    )
    assert "password" not in cleaned
    assert "api_key" not in cleaned
    assert cleaned["x"] == 1
    assert "secrets" in redacted or "password" in redacted
    record = record_python_execution_trace(
        _secret_fixture,
        policy=TraceCollectionPolicy.hermetic(collect_lines=True, include_raw_bodies=True),
    )
    dumped = json.dumps(record.public_record())
    assert "test-only-password-value" not in dumped
    assert "should-not-appear" not in dumped
    private = json.dumps(record.private_record())
    assert "test-only-password-value" not in private
    assert "should-not-appear" not in private
    if record.has_private_raw_bodies:
        raw_dump = json.dumps(dict(record.raw_bodies))
        assert "password" not in raw_dump
        assert "test-only-password-value" not in raw_dump
        assert "should-not-appear" not in raw_dump


def test_test_only_network_denial_records_external_and_does_not_connect() -> None:
    def try_net() -> None:
        socket.create_connection(("127.0.0.1", 1), timeout=0.01)

    record = record_python_execution_trace(
        try_net,
        policy=TraceCollectionPolicy.hermetic(collect_lines=False, deny_network=True),
    )
    assert record.network_denied is True
    assert record.status == TraceStatus.DENIED.value
    assert EventKind.EXTERNAL.value in _kinds(record)
    external = next(event for event in record.events if event.event_kind == EventKind.EXTERNAL.value)
    assert external.payload.get("effect") == "network"
    assert "network" in set(external.unavailable_dimensions) | set(record.public_trace.unavailable_dimensions)
    assert record.accepted_transition_cid is None


def test_cancellation_emits_no_accepted_transition() -> None:
    token = TraceCancellation("stop-early")

    def subject() -> str:
        token.request("stop-early")
        return "must-not-be-accepted"

    record = record_python_execution_trace(
        subject,
        cancellation=token,
        policy=TraceCollectionPolicy.hermetic(collect_lines=False),
    )
    assert record.cancelled is True
    assert record.status == TraceStatus.CANCELLED.value
    assert record.accepted_transition_cid is None
    public = record.public_record()
    assert public["accepted_transition_cid"] is None
    assert public["cancelled"] is True
    assert "accepted_transition" in set(record.public_trace.unavailable_dimensions)
    replayed = replay_deterministic_trace(record)
    assert replayed.cancelled is True
    assert replayed.accepted_transition_cid is None
    assert replayed.replayed is True

    pre = TraceCancellation("already")
    pre.request()
    skipped = record_python_execution_trace(
        _call_fixture,
        cancellation=pre,
        policy=TraceCollectionPolicy.hermetic(),
    )
    assert skipped.cancelled is True
    assert skipped.accepted_transition_cid is None
    assert skipped.status == TraceStatus.CANCELLED.value


def test_private_raw_bodies_never_enter_public_records() -> None:
    record = record_python_execution_trace(
        _call_fixture,
        policy=TraceCollectionPolicy.hermetic(
            collect_lines=False,
            include_raw_bodies=True,
        ),
    )
    assert record.has_private_raw_bodies is True
    assert record.private_trace is not None
    assert record.private_trace.includes_raw_bodies is True
    assert str(record.private_trace.privacy_class) == PrivacyClass.PRIVATE.value
    public = record.public_record()
    assert public["includes_raw_bodies"] is False
    assert public["privacy_class"] == PrivacyClass.PUBLIC.value
    assert "raw_bodies" not in public
    assert "private_trace" not in public
    assert record.public_trace.includes_raw_bodies is False
    assert record.public_trace.raw_execution_state_cids == ()
    dumped = json.dumps(public)
    assert "raw_bodies" not in dumped
    with pytest.raises(PythonExecutionTraceError, match="raw trace bodies"):
        replay_deterministic_trace({**public, "raw_bodies": {"x": 1}})
    with pytest.raises(PythonExecutionTraceError, match="raw trace bodies"):
        replay_deterministic_trace({**public, "includes_raw_bodies": True})


def test_deterministic_promised_replay_preserves_public_identity() -> None:
    policy = TraceCollectionPolicy.hermetic(collect_lines=False)
    first = record_python_execution_trace(_call_fixture, 7, policy=policy)
    second = record_python_execution_trace(_call_fixture, 7, policy=policy)
    assert first.public_trace.execution_trace_cid == second.public_trace.execution_trace_cid
    assert first.python_execution_trace_cid == second.python_execution_trace_cid
    replayed = replay_deterministic_trace(first)
    assert replayed.replayed is True
    assert replayed.public_trace.execution_trace_cid == first.public_trace.execution_trace_cid
    assert replayed.accepted_transition_cid is None
    from_public = replay_deterministic_trace(first.public_record())
    assert from_public.public_trace.event_cids == first.public_trace.event_cids
    assert from_public.replayed is True
    assert from_public.has_private_raw_bodies is False


def test_line_detail_is_policy_bounded() -> None:
    def many_lines() -> int:
        total = 0
        for index in range(20):
            total += index
        return total

    record = record_python_execution_trace(
        many_lines,
        policy=TraceCollectionPolicy.hermetic(collect_lines=True, max_line_events=3, max_events=32),
    )
    line_events = [event for event in record.events if event.event_kind == EventKind.LINE.value]
    assert len(line_events) <= 3
    assert record.bounded is True or "line_detail" in set(record.public_trace.unavailable_dimensions)


def test_environment_binding_rejects_host_identity() -> None:
    with pytest.raises(PythonExecutionTraceError, match="non-semantic"):
        PythonExecutionTracer(environment_binding={"hostname": "box"})
    with pytest.raises(PythonExecutionTraceError, match="non-semantic"):
        PythonExecutionTracer(environment_binding={"pid": "1"})


def test_observations_are_admitted_only_for_observed_events() -> None:
    record = record_python_execution_trace(
        _call_fixture,
        policy=TraceCollectionPolicy.hermetic(collect_lines=False),
    )
    assert record.observations
    for observation in record.observations:
        assert observation.event_origin == "observed"
        assert observation.observation_status == "observed"
        assert observation.tree_cid == record.tree_cid
        assert observation.environment_binding_cid == record.environment_binding_cid
