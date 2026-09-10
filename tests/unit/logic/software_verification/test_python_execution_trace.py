"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    PrivacyClass,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    ADMITTED_LANGUAGE,
    IMPORT_DATABASE_OPENED,
    IMPORT_INSTALLER_INVOKED,
    IMPORT_MODEL_LOADED,
    IMPORT_NETWORK_PERFORMED,
    IMPORT_SCAN_PERFORMED,
    IMPORT_SOCKET_OPENED,
    IMPORT_SUBPROCESS_SPAWNED,
    IMPORT_TRACE_HOOKS_INSTALLED,
    IMPORT_WATCHER_STARTED,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    TRACE_CANCELLATION_INTERFACE,
    TRACE_COLLECTION_POLICY_INTERFACE,
    TRACE_REDACTOR_INTERFACE,
    PythonExecutionTraceError,
    PythonExecutionTracer,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceRedactor,
    record_python_execution_trace,
    replay_deterministic_trace,
)


MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "ipfs_datasets_py"
    / "logic"
    / "software_verification"
    / "python_execution_trace.py"
)

SECRET_TOKEN = "s3cret-token-value"
RAW_TOKEN = "PRIVATE_RAW_BODY_TOKEN"
FORBIDDEN_MODULE_IMPORTS = {
    "socket",
    "ssl",
    "subprocess",
    "multiprocessing",
    "sqlite3",
    "duckdb",
    "watchdog",
    "transformers",
    "torch",
    "requests",
    "urllib",
    "http.client",
    "pip",
    "ensurepip",
    "pathlib",
}
FORBIDDEN_MODULE_CALLS = {
    "socket",
    "create_connection",
    "Popen",
    "urlopen",
    "connect",
    "system",
    "settrace",
    "setprofile",
    "walk",
    "rglob",
    "glob",
    "scandir",
    "Observer",
    "pipeline",
}


def _kinds(record) -> list[str]:
    return [str(event.event_kind) for event in record.events]


def _public_blob(record) -> str:
    return json.dumps(record.public_record(), sort_keys=True)


def ping() -> int:
    return pong()


def pong() -> int:
    return 1


def boom() -> int:
    try:
        raise ValueError("bounded")
    except ValueError:
        return 2


def stream() -> object:
    yield "a"
    yield "b"


class _SuspendOnce:
    def __await__(self):
        yield "suspended"
        return "done"


async def awaited() -> str:
    return await _SuspendOnce()


def secrets() -> int:
    password = SECRET_TOKEN
    api_key = SECRET_TOKEN
    return password is not None and api_key is not None


def bulky() -> bool:
    blob = "x" * 80_000
    return len(blob) > 1


def raw_body() -> bool:
    payload = RAW_TOKEN
    return payload == RAW_TOKEN


def try_network() -> int:
    import socket

    socket.socket()
    return 1


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


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


def test_cold_import_flags_remain_inert() -> None:
    assert IMPORT_SCAN_PERFORMED is False
    assert IMPORT_NETWORK_PERFORMED is False
    assert IMPORT_SOCKET_OPENED is False
    assert IMPORT_SUBPROCESS_SPAWNED is False
    assert IMPORT_INSTALLER_INVOKED is False
    assert IMPORT_DATABASE_OPENED is False
    assert IMPORT_WATCHER_STARTED is False
    assert IMPORT_MODEL_LOADED is False
    assert IMPORT_TRACE_HOOKS_INSTALLED is False


def test_module_level_ast_has_no_denied_side_effects() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    calls: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(stmt, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in stmt.names)
        elif isinstance(stmt, ast.ImportFrom):
            if stmt.module:
                imported.add(stmt.module.split(".", 1)[0])
                imported.add(stmt.module)
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                calls.add(_call_name(node.func))
    assert not (imported & FORBIDDEN_MODULE_IMPORTS)
    assert not (calls & FORBIDDEN_MODULE_CALLS)


def test_import_does_not_install_trace_hooks_or_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("denied surface touched at import")

    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(os, "scandir", boom)
    import ipfs_datasets_py.logic.software_verification.python_execution_trace as module

    assert module.IMPORT_TRACE_HOOKS_INSTALLED is False
    assert module.IMPORT_SCAN_PERFORMED is False
    assert sys.gettrace is not boom


def test_call_and_return_events_bind_exact_code_and_environment() -> None:
    environment = {"language": "python", "python_major": "3", "python_minor": "12"}
    record = record_python_execution_trace(
        ping,
        environment_binding=environment,
        source_text="def ping():\n    return pong()\n",
    )
    kinds = set(_kinds(record))
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    assert record.public_trace.language == ADMITTED_LANGUAGE
    assert record.source_cid
    assert record.tree_cid
    assert record.environment_binding_cid
    assert record.public_trace.tree_cid == record.tree_cid
    assert record.public_trace.source_cid == record.source_cid
    assert record.public_trace.environment_binding_cid == record.environment_binding_cid
    for event in record.events:
        assert event.tree_cid == record.tree_cid
        assert event.source_cid == record.source_cid
        assert event.environment_binding_cid == record.environment_binding_cid
        assert event.language == ADMITTED_LANGUAGE
    assert record.accepted_transition is True
    assert record.outcome == "completed"
    names = {event.logical_name for event in record.events}
    assert any("ping" in name for name in names)
    assert any("pong" in name for name in names)


def test_environment_and_source_rebinding_change_identity() -> None:
    first = record_python_execution_trace(
        ping,
        environment_binding={"language": "python", "env": "a"},
        source_text="def ping():\n    return pong()\n",
    )
    second = record_python_execution_trace(
        ping,
        environment_binding={"language": "python", "env": "b"},
        source_text="def ping():\n    return pong()\n",
    )
    third = record_python_execution_trace(
        ping,
        environment_binding={"language": "python", "env": "a"},
        source_text="def ping():\n    return pong()  # changed\n",
    )
    assert first.environment_binding_cid != second.environment_binding_cid
    assert first.public_trace.execution_trace_cid != second.public_trace.execution_trace_cid
    assert first.source_cid != third.source_cid
    assert first.public_trace.execution_trace_cid != third.public_trace.execution_trace_cid


def test_exception_and_handler_events_are_collected() -> None:
    record = record_python_execution_trace(boom)
    kinds = set(_kinds(record))
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    raised = [event for event in record.events if event.event_kind == EventKind.RAISE.value]
    assert raised
    assert raised[0].exception_snapshot_cid is not None
    assert record.exception_snapshots
    assert record.exception_snapshots[0].future_execution is False
    handled = [
        event
        for event in record.events
        if event.event_kind in {EventKind.CATCH.value, EventKind.HANDLER.value}
    ]
    assert handled
    assert any(event.handler_state_cid is not None for event in handled)


def test_yield_events_are_collected_from_generator_functions() -> None:
    record = record_python_execution_trace(stream)
    kinds = _kinds(record)
    assert EventKind.YIELD.value in kinds
    yields = [event for event in record.events if event.event_kind == EventKind.YIELD.value]
    assert len(yields) >= 2
    assert record.accepted_transition is True


def test_await_events_are_collected_from_coroutine_functions() -> None:
    record = record_python_execution_trace(awaited)
    kinds = set(_kinds(record))
    assert EventKind.AWAIT.value in kinds or EventKind.YIELD.value in kinds
    assert record.outcome == "completed"
    assert record.result_summary.get("result") == "done"


def test_line_events_are_policy_bounded() -> None:
    policy = TraceCollectionPolicy(collect_line_events=True, max_line_events=1, max_events=32)
    record = record_python_execution_trace(ping, policy=policy)
    line_events = [event for event in record.events if event.event_kind == EventKind.LINE.value]
    assert len(line_events) <= 1
    disabled = TraceCollectionPolicy(collect_line_events=False)
    quiet = record_python_execution_trace(ping, policy=disabled)
    assert EventKind.LINE.value not in _kinds(quiet)


def test_payload_bounds_do_not_raise_and_stay_within_limit() -> None:
    policy = TraceCollectionPolicy(max_payload_bytes=512, max_string_chars=32)
    record = record_python_execution_trace(bulky, policy=policy)
    assert record.events
    for event in record.events:
        encoded = json.dumps(event.payload)
        assert len(encoded.encode("utf-8")) <= 16_384
    blob = _public_blob(record)
    assert "x" * 80_000 not in blob


def test_secret_redaction_strips_secret_fields() -> None:
    record = record_python_execution_trace(secrets)
    blob = _public_blob(record)
    assert SECRET_TOKEN not in blob
    assert "password" not in blob
    assert "api_key" not in blob
    private = json.dumps(record.to_dict())
    assert SECRET_TOKEN not in private
    assert record.completeness_claim != CompletenessClaim.FULL_STATE.value
    assert record.public_trace.completeness_claim != CompletenessClaim.FULL_STATE.value


def test_network_is_denied_and_recorded_as_external(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    called: list[bool] = []
    real = socket.socket

    def boom(*_args: object, **_kwargs: object) -> object:
        called.append(True)
        return real(*_args, **_kwargs)

    monkeypatch.setattr(socket, "socket", boom)
    record = record_python_execution_trace(try_network)
    assert called == []
    assert record.accepted_transition is False
    assert record.outcome == "denied"
    assert EventKind.EXTERNAL.value in _kinds(record)
    effects = [
        event.payload.get("effect")
        for event in record.events
        if event.event_kind == EventKind.EXTERNAL.value
    ]
    assert any(effect and "socket" in str(effect) for effect in effects)


def test_cancellation_before_start_emits_no_accepted_transition() -> None:
    token = TraceCancellation()
    token.cancel("stop-before-start")
    record = record_python_execution_trace(ping, cancellation=token)
    assert token.accepted_transition is False
    assert record.accepted_transition is False
    assert record.outcome == "cancelled"
    assert record.cancellation["requested"] is True
    assert record.cancellation["accepted_transition"] is False
    public = record.public_record()
    assert public["accepted_transition"] is False
    assert public["cancellation"]["accepted_transition"] is False
    assert "remaining_trace" in record.unavailable_dimensions


def test_mid_execution_cancellation_emits_no_accepted_transition() -> None:
    token = TraceCancellation()

    def subject() -> int:
        token.cancel("mid")
        return ping()

    record = record_python_execution_trace(subject, cancellation=token)
    assert record.accepted_transition is False
    assert record.outcome == "cancelled"
    assert record.cancellation["accepted_transition"] is False
    public = record.public_record()
    assert public["accepted_transition"] is False
    assert EventKind.EXIT.value not in _kinds(record) or record.accepted_transition is False


def test_private_raw_bodies_never_enter_public_records() -> None:
    policy = TraceCollectionPolicy(include_raw_bodies=True, capture_locals=True)
    record = record_python_execution_trace(raw_body, policy=policy)
    assert record.private_trace.includes_raw_bodies is True
    assert record.private_trace.privacy_class == PrivacyClass.PRIVATE.value
    assert record.private_trace.raw_execution_state_cids
    public = record.public_record()
    assert public["includes_raw_bodies"] is False
    assert public["public_trace"]["includes_raw_bodies"] is False
    assert public["public_trace"]["raw_execution_state_cids"] == []
    assert public["public_trace"]["privacy_class"] == PrivacyClass.PUBLIC.value
    assert "private_trace" not in public
    assert "private_states" not in public
    blob = json.dumps(public)
    assert RAW_TOKEN not in blob
    assert record.public_trace.includes_raw_bodies is False
    assert record.public_trace.raw_execution_state_cids == ()
    redactor = TraceRedactor()
    projected = redactor.public_record(record)
    assert projected["includes_raw_bodies"] is False
    assert RAW_TOKEN not in json.dumps(projected)


def test_deterministic_promised_replay_matches_public_identity() -> None:
    environment = {"language": "python", "suite": "replay"}
    source = "def ping():\n    return pong()\n"
    first = record_python_execution_trace(
        ping, environment_binding=environment, source_text=source
    )
    second = record_python_execution_trace(
        ping, environment_binding=environment, source_text=source
    )
    assert first.public_trace.execution_trace_cid == second.public_trace.execution_trace_cid
    replay = replay_deterministic_trace(
        ping,
        previous=first,
        environment_binding=environment,
        source_text=source,
    )
    assert replay.matched is True
    assert replay.replayed_public_trace_cid == first.public_trace.execution_trace_cid
    assert replay.accepted_transition is True


def test_replay_of_cancelled_or_denied_traces_is_unavailable() -> None:
    token = TraceCancellation()
    token.cancel("no-replay")
    cancelled = record_python_execution_trace(ping, cancellation=token)
    with pytest.raises(PythonExecutionTraceError, match="cancelled"):
        replay_deterministic_trace(ping, previous=cancelled)
    denied = record_python_execution_trace(try_network)
    with pytest.raises(PythonExecutionTraceError, match="denied|external"):
        replay_deterministic_trace(try_network, previous=denied)


def test_non_python_language_is_typed_unavailable() -> None:
    with pytest.raises(PythonExecutionTraceError, match="Python only"):
        TraceCollectionPolicy(language="javascript")
    with pytest.raises(PythonExecutionTraceError, match="Python only"):
        TraceCollectionPolicy(language="shell")


def test_observations_are_admitted_and_predicted_origins_are_absent() -> None:
    record = record_python_execution_trace(ping)
    assert record.observations
    for observation in record.observations:
        assert observation.event_origin == "observed"
        assert observation.observation_status == "observed"
    for event in record.events:
        assert event.event_origin == "observed"


def test_in_memory_collection_does_not_walk_the_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("filesystem scan is forbidden during hermetic collection")

    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(os, "scandir", boom)
    monkeypatch.setattr(Path, "rglob", boom)
    monkeypatch.setattr(Path, "glob", boom)
    record = record_python_execution_trace(pong)
    assert record.events
    assert record.public_trace.event_cids


def test_policy_identity_is_stable_and_capture_profile_binds() -> None:
    first = TraceCollectionPolicy(max_events=128, collect_line_events=False)
    second = TraceCollectionPolicy(max_events=128, collect_line_events=False)
    assert first.trace_collection_policy_cid == second.trace_collection_policy_cid
    changed = TraceCollectionPolicy(max_events=256, collect_line_events=False)
    assert first.trace_collection_policy_cid != changed.trace_collection_policy_cid
    record = record_python_execution_trace(pong, policy=first)
    assert record.policy.trace_collection_policy_cid == first.trace_collection_policy_cid


def test_public_record_never_claims_raw_or_accepted_cancel() -> None:
    token = TraceCancellation()
    token.cancel("gate")
    record = record_python_execution_trace(ping, cancellation=token)
    public = record.public_record()
    assert public["accepted_transition"] is False
    assert public["includes_raw_bodies"] is False
    dumped = json.dumps(public)
    assert '"accepted_transition": true' not in dumped
    assert '"includes_raw_bodies": true' not in dumped
