"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    PrivacyClass,
    ProgramEvent,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    ACCEPTED_TRANSITION_DISPOSITION,
    IMPORT_DATABASE_OPENED,
    IMPORT_INSTALLER_INVOKED,
    IMPORT_MODEL_LOADED,
    IMPORT_NETWORK_OPENED,
    IMPORT_SCAN_PERFORMED,
    IMPORT_SIDE_EFFECTS_PERFORMED,
    IMPORT_SOCKET_OPENED,
    IMPORT_SUBPROCESS_SPAWNED,
    IMPORT_TRACE_HOOK_INSTALLED,
    IMPORT_WATCHER_STARTED,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    TRACE_CANCELLATION_INTERFACE,
    TRACE_COLLECTION_POLICY_INTERFACE,
    TRACE_REDACTOR_INTERFACE,
    PythonExecutionNetworkDenied,
    PythonExecutionTraceError,
    PythonExecutionTracer,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceRedactor,
    TransitionDisposition,
    record_python_execution_trace,
    replay_deterministic_trace,
)


MODULE_PATH = Path(
    sys.modules["ipfs_datasets_py.logic.software_verification.python_execution_trace"].__file__
).resolve()
FORBIDDEN_IMPORTS = {
    "socket",
    "subprocess",
    "sqlite3",
    "duckdb",
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
    "urllib.request",
    "urllib3",
    "torch",
    "transformers",
    "watchdog",
    "pip",
    "installer",
    "threading",
    "multiprocessing",
    "pathlib",
    "os",
    "pickle",
    "http.client",
}


def add(left: int, right: int) -> int:
    return left + right


def boom() -> int:
    try:
        raise ValueError("bounded")
    except ValueError:
        return 7


def produce() -> list[int]:
    def gen() -> object:
        yield 1
        yield 2

    return list(gen())


def await_one() -> int:
    async def inner() -> int:
        import asyncio

        await asyncio.sleep(0)
        return 4

    import asyncio

    return asyncio.run(inner())


def leak() -> int:
    password = "test-only-password-value"
    api_key = "should-not-appear"
    visible = 1
    return visible + len(password) * 0 + len(api_key) * 0


def huge() -> str:
    blob = "x" * 5000
    return blob


def _kinds(record) -> set[str]:
    return set(record.event_kinds())


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
    assert TRACE_COLLECTION_POLICY_INTERFACE == "TraceCollectionPolicy@1"
    assert TRACE_REDACTOR_INTERFACE == "TraceRedactor@1"
    assert TRACE_CANCELLATION_INTERFACE == "TraceCancellation@1"
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)
    assert PythonExecutionTracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE
    assert TraceCollectionPolicy.INTERFACE == TRACE_COLLECTION_POLICY_INTERFACE
    assert TraceRedactor.INTERFACE == TRACE_REDACTOR_INTERFACE
    assert TraceCancellation.INTERFACE == TRACE_CANCELLATION_INTERFACE


def test_import_is_inert_and_installs_no_hooks() -> None:
    assert IMPORT_SIDE_EFFECTS_PERFORMED is False
    assert IMPORT_SCAN_PERFORMED is False
    assert IMPORT_NETWORK_OPENED is False
    assert IMPORT_SOCKET_OPENED is False
    assert IMPORT_INSTALLER_INVOKED is False
    assert IMPORT_SUBPROCESS_SPAWNED is False
    assert IMPORT_DATABASE_OPENED is False
    assert IMPORT_WATCHER_STARTED is False
    assert IMPORT_MODEL_LOADED is False
    assert IMPORT_TRACE_HOOK_INSTALLED is False


def test_module_source_has_no_import_time_side_effects() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
                imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            raise AssertionError("module-level call is forbidden at import")
    assert imported.isdisjoint(FORBIDDEN_IMPORTS)
    module_calls = [
        ast.dump(node)
        for node in tree.body
        if isinstance(node, ast.Expr)
    ]
    assert not any("settrace" in item or "setprofile" in item for item in module_calls)


def test_call_return_and_line_events_bind_exact_identities() -> None:
    record = record_python_execution_trace(add, args=(1, 2))
    kinds = _kinds(record)
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    assert EventKind.LINE.value in kinds
    assert record.public_trace.tree_cid == record.tree_cid
    assert record.public_trace.source_cid == record.source_cid
    assert record.public_trace.environment_binding_cid == record.environment_binding_cid
    for event in record.events:
        assert event.tree_cid == record.tree_cid
        assert event.source_cid == record.source_cid
        assert event.environment_binding_cid == record.environment_binding_cid
        assert event.subject_cid == record.subject_cid
        assert event.line is not None
        assert event.logical_name
    call = next(event for event in record.events if event.event_kind == EventKind.CALL.value)
    assert call.logical_name.endswith("add")
    assert call.stack_frame_cids
    assert record.accepted_transition is False
    assert record.transition_disposition != ACCEPTED_TRANSITION_DISPOSITION


def test_exception_and_handler_events_are_collected() -> None:
    record = record_python_execution_trace(boom)
    kinds = _kinds(record)
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds
    assert EventKind.HANDLER.value in kinds
    raised = next(event for event in record.events if event.event_kind == EventKind.RAISE.value)
    assert raised.exception_snapshot_cid is not None
    caught = next(event for event in record.events if event.event_kind == EventKind.CATCH.value)
    assert caught.handler_state_cid is not None
    assert record.exceptions
    assert record.handlers
    assert record.result_summary["value"] == 7


def test_yield_events_are_collected() -> None:
    record = record_python_execution_trace(produce)
    assert EventKind.YIELD.value in _kinds(record)
    assert record.result_summary["value"]["items"] == [1, 2]


def test_await_events_are_collected() -> None:
    record = record_python_execution_trace(await_one)
    kinds = _kinds(record)
    assert EventKind.AWAIT.value in kinds
    assert EventKind.RETURN.value in kinds
    assert record.result_summary["value"] == 4


def test_payload_bounds_truncate_large_locals() -> None:
    policy = TraceCollectionPolicy(max_payload_bytes=256, max_summary_chars=16)
    record = record_python_execution_trace(huge, policy=policy)
    returned = next(event for event in record.events if event.event_kind == EventKind.RETURN.value)
    blob = json.dumps(returned.payload)
    assert "x" * 64 not in blob
    assert returned.payload.get("bounded") is True or "truncated" in blob or "length" in blob


def test_secret_redaction_omits_private_values() -> None:
    record = record_python_execution_trace(leak)
    returned = next(event for event in record.events if event.event_kind == EventKind.RETURN.value)
    payload = json.dumps(returned.payload)
    assert "test-only-password-value" not in payload
    assert "should-not-appear" not in payload
    assert "password" not in returned.payload.get("locals", {})
    assert "api_key" not in returned.payload.get("locals", {})
    assert "visible" in returned.payload.get("locals", {})
    public = json.dumps(record.to_public_dict())
    assert "test-only-password-value" not in public
    assert "should-not-appear" not in public
    assert "events" not in record.to_public_dict()
    assert "states" not in record.to_public_dict()
    assert record.redaction_profile.completeness_claim != CompletenessClaim.FULL_STATE.value or (
        "password" in record.redaction_profile.redacted_dimensions
        or "api_key" in record.redaction_profile.redacted_dimensions
        or "raw_body" in record.redaction_profile.redacted_dimensions
    )


def test_private_raw_bodies_never_enter_public_records() -> None:
    record = record_python_execution_trace(add, args=(2, 3))
    assert record.private_trace.includes_raw_bodies is True
    assert record.private_trace.privacy_class == PrivacyClass.PRIVATE.value
    assert record.public_trace.includes_raw_bodies is False
    assert record.public_trace.privacy_class == PrivacyClass.PUBLIC.value
    assert record.public_trace.raw_execution_state_cids == ()
    assert record.public_trace.execution_trace_cid != record.private_trace.execution_trace_cid
    public = record.to_public_dict()
    assert public["accepted_transition"] is False
    assert public["public_trace"]["includes_raw_bodies"] is False
    assert public["public_trace"]["raw_execution_state_cids"] == []
    assert "events" not in public
    assert "states" not in public
    encoded = json.dumps(public)
    for event in record.events:
        if event.payload:
            assert json.dumps(event.payload) not in encoded or event.payload == {"phase": "call"}


def test_test_only_network_isolation_denies_selected_externals() -> None:
    def probe() -> None:
        import socket

        socket.create_connection(("127.0.0.1", 1), timeout=0.01)

    record = record_python_execution_trace(probe)
    assert EventKind.EXTERNAL.value in _kinds(record)
    external = next(event for event in record.events if event.event_kind == EventKind.EXTERNAL.value)
    assert external.payload.get("denied") is True
    assert record.error_summary is not None
    assert record.error_summary["type"] == PythonExecutionNetworkDenied.__name__
    assert record.accepted_transition is False


def test_isolation_is_restored_after_collection() -> None:
    import socket

    original = socket.create_connection

    def probe() -> None:
        socket.create_connection(("127.0.0.1", 1), timeout=0.01)

    record_python_execution_trace(probe)
    assert socket.create_connection is original


def test_cancellation_emits_no_accepted_transition() -> None:
    token = TraceCancellation()

    def work() -> int:
        total = 0
        for index in range(30):
            if index == 2:
                token.cancel("stop")
            total += index
        return total

    record = record_python_execution_trace(work, cancellation=token)
    assert record.cancelled is True
    assert record.accepted_transition is False
    assert record.transition_disposition == TransitionDisposition.CANCELLED.value
    assert record.transition_disposition != ACCEPTED_TRANSITION_DISPOSITION
    public = record.to_public_dict()
    assert public["accepted_transition"] is False
    assert public["cancelled"] is True
    replay = replay_deterministic_trace(record, promised_events=record.events)
    assert replay.accepted_transition is False
    assert replay.cancelled is True
    assert "remaining_trace" in record.public_trace.unavailable_dimensions or (
        record.public_trace.completeness_claim != CompletenessClaim.FULL_STATE.value
    )


def test_deterministic_promised_replay_matches_public_identity() -> None:
    first = record_python_execution_trace(add, args=(1, 2))
    second = record_python_execution_trace(add, args=(1, 2))
    assert first.tree_cid == second.tree_cid
    assert first.source_cid == second.source_cid
    assert first.environment_binding_cid == second.environment_binding_cid
    assert first.subject_cid == second.subject_cid
    assert first.public_trace.execution_trace_cid == second.public_trace.execution_trace_cid
    replay = replay_deterministic_trace(first, promised_events=first.events)
    assert replay.execution_trace_cid == first.public_trace.execution_trace_cid
    assert replay.event_cids == first.public_trace.event_cids
    assert replay.deterministic is True
    assert replay.accepted_transition is False
    with pytest.raises(PythonExecutionTraceError, match="promised event count"):
        replay_deterministic_trace(first, promised_events=first.events[:-1])
    with pytest.raises(PythonExecutionTraceError, match="requires a PythonExecutionTraceRecord"):
        replay_deterministic_trace(object())  # type: ignore[arg-type]


def test_replay_does_not_reinvoke_the_subject() -> None:
    calls = {"count": 0}

    def counted(value: int) -> int:
        calls["count"] += 1
        return value + 1

    record = record_python_execution_trace(counted, args=(3,))
    assert calls["count"] == 1
    replay_deterministic_trace(record, promised_events=record.events)
    assert calls["count"] == 1


def test_trace_hooks_are_restored() -> None:
    previous = sys.gettrace()
    record_python_execution_trace(add, args=(4, 5))
    assert sys.gettrace() is previous
    assert sys.getprofile() is None or sys.getprofile() is not PythonExecutionTracer._profile


def test_policy_bounds_stop_unbounded_line_detail() -> None:
    policy = TraceCollectionPolicy(max_events=8, max_line_events=2)

    def many_lines() -> int:
        value = 0
        value += 1
        value += 1
        value += 1
        value += 1
        value += 1
        return value

    record = record_python_execution_trace(many_lines, policy=policy)
    assert len(record.events) <= 8
    assert record.trace_status in {"bounded", "completed", "failed"}
    line_events = [event for event in record.events if event.event_kind == EventKind.LINE.value]
    assert len(line_events) <= 2


def test_events_are_program_event_records() -> None:
    record = record_python_execution_trace(add, args=(8, 1))
    assert record.events
    assert all(isinstance(event, ProgramEvent) for event in record.events)
    assert record.public_trace.event_cids == tuple(event.program_event_cid for event in record.events)
