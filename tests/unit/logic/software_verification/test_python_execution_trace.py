"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import ast
import json
import os
import socket as socket_module
import types
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    EventKind,
    ExecutionTrace,
    PrivacyClass,
    ProgramEvent,
    observe_program_event,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    ADMITTED_LANGUAGE,
    IMPORT_DATABASE_OPENED,
    IMPORT_INSTALLER_STARTED,
    IMPORT_MODEL_LOADED,
    IMPORT_NETWORK_LOADED,
    IMPORT_REPO_SCAN_PERFORMED,
    IMPORT_SIDE_EFFECTS_PERFORMED,
    IMPORT_SOCKET_CONNECTED,
    IMPORT_SUBPROCESS_STARTED,
    IMPORT_WATCHER_STARTED,
    PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE,
    PYTHON_EXECUTION_TRACE_RECEIPT_INTERFACE,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    TRACE_CANCELLATION_INTERFACE,
    TRACE_COLLECTION_POLICY_INTERFACE,
    TRACE_REDACTOR_INTERFACE,
    PythonExecutionTraceError,
    PythonExecutionTracer,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceRedactor,
    default_environment_binding,
    record_python_execution_trace,
    replay_deterministic_trace,
)


BANNED_IMPORT_ROOTS = frozenset(
    {
        "torch",
        "transformers",
        "requests",
        "urllib3",
        "httpx",
        "watchdog",
        "duckdb",
        "sqlite3",
        "psycopg2",
        "socket",
        "subprocess",
        "multiprocessing",
        "asyncio",
    }
)


def _add(left: int, right: int) -> int:
    return left + right


def _caught() -> str:
    try:
        raise ValueError("boom")
    except ValueError:
        return "caught"


def _uncaught() -> None:
    raise RuntimeError("fail")


def _yield_two() -> list[int]:
    def gen() -> object:
        yield 1
        yield 2

    return list(gen())


def _await_value() -> int:
    async def inner() -> int:
        return 7

    async def outer() -> int:
        return await inner()

    driver = outer()
    sent: object = None
    current = driver
    for _ in range(8):
        try:
            yielded = current.send(sent)
        except StopIteration as stop:
            if current is driver:
                return int(stop.value)
            sent = stop.value
            current = driver
            continue
        if type(yielded).__name__ == "coroutine":
            current = yielded
            sent = None
            continue
        sent = yielded
    raise AssertionError("await fixture did not complete")


def _secret_holder(password: str = "s3cret-value", api_key: str = "k-live") -> int:
    bundle = {"n": 1, "password": "s3cret-value", "api_key": "k-live"}
    secret = "hidden-secret"
    return bundle["n"] + len(password) + len(api_key) + len(secret)


def _huge_local() -> int:
    blob = "a" * 100_000
    return len(blob)


def _many_lines() -> int:
    value = 0
    value += 1
    value += 1
    value += 1
    value += 1
    value += 1
    return value


def test_public_interfaces_and_predicted_symbols_are_versioned() -> None:
    assert PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
    assert TRACE_COLLECTION_POLICY_INTERFACE == "TraceCollectionPolicy@1"
    assert TRACE_REDACTOR_INTERFACE == "TraceRedactor@1"
    assert TRACE_CANCELLATION_INTERFACE == "TraceCancellation@1"
    assert PYTHON_EXECUTION_TRACE_RECEIPT_INTERFACE == "PythonExecutionTraceReceipt@1"
    assert PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE == "PythonExecutionReplayReceipt@1"
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)
    assert PythonExecutionTracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE
    assert TraceCollectionPolicy.INTERFACE == TRACE_COLLECTION_POLICY_INTERFACE
    assert TraceRedactor.INTERFACE == TRACE_REDACTOR_INTERFACE
    assert TraceCancellation.INTERFACE == TRACE_CANCELLATION_INTERFACE


def test_cold_import_has_no_network_socket_installer_subprocess_database_scan_watcher_or_model_loads() -> None:
    assert IMPORT_SIDE_EFFECTS_PERFORMED is False
    assert IMPORT_NETWORK_LOADED is False
    assert IMPORT_SOCKET_CONNECTED is False
    assert IMPORT_INSTALLER_STARTED is False
    assert IMPORT_SUBPROCESS_STARTED is False
    assert IMPORT_DATABASE_OPENED is False
    assert IMPORT_REPO_SCAN_PERFORMED is False
    assert IMPORT_WATCHER_STARTED is False
    assert IMPORT_MODEL_LOADED is False

    module = __import__(
        "ipfs_datasets_py.logic.software_verification.python_execution_trace",
        fromlist=["record_python_execution_trace"],
    )
    imported_modules = {
        getattr(value, "__name__", "").split(".")[0]
        for value in vars(module).values()
        if isinstance(value, types.ModuleType)
    }
    assert imported_modules.isdisjoint(BANNED_IMPORT_ROOTS)

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    top_level: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.add(node.module.split(".")[0])
    assert top_level.isdisjoint(BANNED_IMPORT_ROOTS)


def test_in_memory_recording_does_not_walk_the_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("repository scan is forbidden during hermetic tracing")

    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(os, "scandir", boom)
    monkeypatch.setattr(Path, "rglob", boom)
    monkeypatch.setattr(Path, "glob", boom)
    receipt = record_python_execution_trace(_add, 2, 3)
    assert receipt.result_summary["value"] == 5
    assert receipt.accepted_transition is False


def test_records_call_and_return_with_exact_bindings() -> None:
    receipt = record_python_execution_trace(_add, 2, 3)
    kinds = set(receipt.event_kinds)
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    assert receipt.language == ADMITTED_LANGUAGE
    assert receipt.tree_cid
    assert receipt.source_cid
    assert receipt.environment_binding_cid
    assert receipt.capture_profile_cid
    for event in receipt.events:
        assert event.tree_cid == receipt.tree_cid
        assert event.source_cid == receipt.source_cid
        assert event.environment_binding_cid == receipt.environment_binding_cid
        assert event.code_cid
        assert event.logical_name
        assert str(event.event_origin) == "observed"
    assert receipt.private_trace.tree_cid == receipt.tree_cid
    assert receipt.public_trace.tree_cid == receipt.tree_cid
    assert receipt.status == "recorded"
    assert receipt.accepted_transition is False
    env = default_environment_binding()
    assert env["language"] == "python"
    assert "hostname" not in env
    assert "pid" not in env


def test_every_event_binds_tree_source_code_and_environment() -> None:
    receipt = record_python_execution_trace(_caught)
    assert receipt.events
    for event in receipt.events:
        assert event.tree_cid == receipt.tree_cid
        assert event.source_cid == receipt.source_cid
        assert event.code_cid
        assert event.environment_binding_cid == receipt.environment_binding_cid
        decoded = ProgramEvent.from_dict(event.to_dict())
        assert decoded.program_event_cid == event.program_event_cid


def test_records_exception_and_handler_fixtures() -> None:
    receipt = record_python_execution_trace(_caught)
    kinds = set(receipt.event_kinds)
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    raise_events = [event for event in receipt.events if event.event_kind == EventKind.RAISE.value]
    assert raise_events
    assert raise_events[0].exception_snapshot_cid
    handler_events = [
        event
        for event in receipt.events
        if event.event_kind in {EventKind.CATCH.value, EventKind.HANDLER.value}
    ]
    assert handler_events
    assert handler_events[0].handler_state_cid
    failed = record_python_execution_trace(_uncaught)
    assert failed.target_exception_type == "RuntimeError"
    assert EventKind.RAISE.value in set(failed.event_kinds)
    assert failed.accepted_transition is False


def test_records_yield_and_await_fixtures() -> None:
    yielded = record_python_execution_trace(_yield_two)
    assert EventKind.YIELD.value in set(yielded.event_kinds)
    assert yielded.result_summary["value"] == [1, 2]
    awaited = record_python_execution_trace(_await_value)
    assert EventKind.AWAIT.value in set(awaited.event_kinds)
    assert awaited.result_summary["value"] == 7


def test_payload_bounds_are_enforced() -> None:
    policy = TraceCollectionPolicy(
        max_local_chars=24,
        max_payload_bytes=512,
        max_local_items=4,
        collect_lines=True,
    )
    receipt = record_python_execution_trace(_huge_local, policy=policy)
    blob = json.dumps([event.to_dict() for event in receipt.events])
    assert "a" * 1000 not in blob
    for state in receipt.states:
        encoded = json.dumps(state.to_dict())
        assert len(encoded) < 16_384
        locals_map = dict(state.observed_state.get("locals", {}))
        blob_value = locals_map.get("blob")
        if isinstance(blob_value, str):
            assert len(blob_value) <= 24


def test_line_events_are_policy_cost_bounded() -> None:
    policy = TraceCollectionPolicy(max_line_events=2, max_events=64)
    receipt = record_python_execution_trace(_many_lines, policy=policy)
    line_count = sum(kind == EventKind.LINE.value for kind in receipt.event_kinds)
    assert line_count <= 2
    assert "line_suffix" in receipt.private_trace.unavailable_dimensions


def test_secrets_are_redacted_from_records() -> None:
    redactor = TraceRedactor()
    cleaned = redactor.redact({"password": "s3cret-value", "n": 1, "api_key": "k-live"})
    assert cleaned == {"n": 1}
    assert "secrets" in redactor.redacted_dimensions
    receipt = record_python_execution_trace(_secret_holder)
    public = json.dumps(receipt.public_record())
    private_events = json.dumps([event.to_dict() for event in receipt.events])
    private_states = json.dumps([state.to_dict() for state in receipt.states])
    for leak in ("s3cret-value", "k-live", "hidden-secret"):
        assert leak not in public
        assert leak not in private_events
        assert leak not in private_states
    secret_keys = {"password", "api_key", "secret"}
    for event in receipt.events:
        payload_keys = {str(key).lower() for key in dict(event.payload)}
        assert payload_keys.isdisjoint(secret_keys)
    for state in receipt.states:
        locals_map = dict(dict(state.observed_state).get("locals", {}))
        lowered = {str(key).lower() for key in locals_map}
        assert lowered.isdisjoint(secret_keys)
    assert receipt.accepted_transition is False


def test_network_is_denied_during_collection_and_recorded_as_external() -> None:
    def probe() -> str:
        socket_module.create_connection(("203.0.113.1", 9), timeout=0.05)
        return "connected"

    receipt = record_python_execution_trace(probe)
    assert receipt.network_denied is True
    assert receipt.accepted_transition is False
    kinds = set(receipt.event_kinds)
    assert EventKind.EXTERNAL.value in kinds or receipt.target_exception_type
    assert receipt.result_summary.get("value") != "connected"
    for event in receipt.events:
        payload = dict(event.payload)
        assert "hostname" not in payload


def test_cancellation_emits_no_accepted_transition() -> None:
    token = TraceCancellation()

    def work() -> int:
        token.cancel("operator-stop")
        total = 0
        for item in range(8):
            total += item
        return total

    receipt = record_python_execution_trace(work, cancellation=token)
    assert receipt.cancelled is True
    assert receipt.status == "cancelled"
    assert receipt.accepted_transition is False
    assert receipt.cancellation_reason == "operator-stop"
    public = receipt.public_record()
    assert public["accepted_transition"] is False
    assert public["status"] != "accepted"
    replayed = replay_deterministic_trace(receipt, target=work)
    assert replayed.accepted_transition is False
    assert replayed.matched is False

    early = TraceCancellation()
    early.cancel("before-start")
    empty = record_python_execution_trace(_add, 1, 1, cancellation=early)
    assert empty.cancelled is True
    assert empty.accepted_transition is False
    assert empty.status == "cancelled"


def test_deterministic_promised_replay_matches() -> None:
    first = record_python_execution_trace(_add, 4, 5)
    second = record_python_execution_trace(_add, 4, 5)
    assert first.event_kinds == second.event_kinds
    assert first.public_trace.execution_trace_cid == second.public_trace.execution_trace_cid
    assert first.private_trace.execution_trace_cid == second.private_trace.execution_trace_cid
    replayed = replay_deterministic_trace(
        first,
        target=_add,
        args=(4, 5),
    )
    assert replayed.event_kind_sequence_equal is True
    assert replayed.matched is True
    assert replayed.accepted_transition is False
    assert replayed.replayed_public_trace_cid == first.public_trace.execution_trace_cid
    rehash = replay_deterministic_trace(first)
    assert rehash.matched is True
    assert rehash.accepted_transition is False
    event_replay = replay_deterministic_trace(first.events)
    assert event_replay.matched is True


def test_public_records_never_include_private_raw_trace_bodies() -> None:
    policy = TraceCollectionPolicy(include_raw_bodies=True)
    receipt = record_python_execution_trace(_add, 1, 2, policy=policy)
    assert receipt.private_trace.includes_raw_bodies is True
    assert str(receipt.private_trace.privacy_class) == PrivacyClass.PRIVATE.value
    assert receipt.private_trace.raw_execution_state_cids
    public_trace = receipt.public_trace
    assert public_trace.includes_raw_bodies is False
    assert public_trace.raw_execution_state_cids == ()
    assert str(public_trace.privacy_class) == PrivacyClass.PUBLIC.value
    public = receipt.public_record()
    assert "private_trace" not in public
    assert public["public_trace"]["includes_raw_bodies"] is False
    assert public["public_trace"]["raw_execution_state_cids"] == []
    encoded = json.dumps(public)
    assert "s3cret" not in encoded
    assert receipt.accepted_transition is False
    observed = [
        observe_program_event(event)
        for event in receipt.events
        if event.observation_admissible
    ]
    assert observed


def test_tracer_rejects_non_python_callables() -> None:
    with pytest.raises(PythonExecutionTraceError, match="Python function or method"):
        record_python_execution_trace(len, [1, 2, 3])
    with pytest.raises(PythonExecutionTraceError, match="event_kinds"):
        TraceCollectionPolicy(event_kinds=())


def test_promised_execution_trace_identity_rehashes() -> None:
    receipt = record_python_execution_trace(_add, 8, 1)
    rebuilt = ExecutionTrace.from_dict(receipt.public_trace.to_dict())
    assert rebuilt.execution_trace_cid == receipt.public_trace.execution_trace_cid
    replayed = replay_deterministic_trace(receipt.public_trace)
    assert replayed.matched is True
    assert replayed.accepted_transition is False
