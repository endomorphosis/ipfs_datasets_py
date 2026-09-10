"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import ast
import importlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    PrivacyClass,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    IMPORT_SCAN_PERFORMED,
    IMPORT_SIDE_EFFECTS_PERFORMED,
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


MODULE_NAME = "ipfs_datasets_py.logic.software_verification.python_execution_trace"
MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "ipfs_datasets_py"
    / "logic"
    / "software_verification"
    / "python_execution_trace.py"
)


def ping() -> int:
    return pong()


def pong() -> int:
    return 1


def handled() -> str:
    try:
        raise ValueError("bounded")
    except ValueError:
        return "ok"


def unhandled() -> None:
    raise KeyError("missing")


def producer() -> list[int]:
    def gen() -> object:
        yield 1
        yield 2
        return 3

    return list(gen())


async def inner_async() -> int:
    return 1


async def outer_async() -> int:
    return await inner_async()


def secret_holder() -> str:
    password = "s3cret"
    token = "not-exported"
    return password[:0] + "ok" + token[:0]


def bulky() -> str:
    payload = "Q" * 80_000
    return payload[:1]


def _kinds(record: object) -> list[str]:
    return [str(event.event_kind) for event in record.events]  # type: ignore[attr-defined]


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
    assert TRACE_COLLECTION_POLICY_INTERFACE == "TraceCollectionPolicy@1"
    assert TRACE_REDACTOR_INTERFACE == "TraceRedactor@1"
    assert TRACE_CANCELLATION_INTERFACE == "TraceCancellation@1"
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)
    tracer = PythonExecutionTracer()
    assert tracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE
    policy = TraceCollectionPolicy()
    assert policy.INTERFACE == TRACE_COLLECTION_POLICY_INTERFACE
    assert TraceRedactor.INTERFACE == TRACE_REDACTOR_INTERFACE
    token = TraceCancellation()
    assert token.INTERFACE == TRACE_CANCELLATION_INTERFACE
    assert token.accepted_transition is False


def test_import_constants_claim_no_side_effects() -> None:
    assert IMPORT_SIDE_EFFECTS_PERFORMED is False
    assert IMPORT_SCAN_PERFORMED is False


def test_module_ast_has_no_import_time_effects() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden_roots = {
        "socket",
        "subprocess",
        "sqlite3",
        "duckdb",
        "requests",
        "urllib3",
        "httpx",
        "torch",
        "transformers",
        "watchdog",
        "pathlib",
    }
    forbidden_attrs = {
        "create_connection",
        "Popen",
        "run",
        "system",
        "connect",
        "urlopen",
        "rglob",
        "walk",
        "scandir",
        "settrace",
        "setprofile",
        "addaudithook",
    }

    def dotted(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = dotted(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            name = dotted(node.value.func)
            root = name.split(".", 1)[0]
            attr = name.rsplit(".", 1)[-1]
            if root in forbidden_roots or attr in forbidden_attrs:
                raise AssertionError(f"import-time call {name}")
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            name = dotted(node.value.func)
            attr = name.rsplit(".", 1)[-1]
            if attr in {"settrace", "Popen", "create_connection", "rglob", "walk"}:
                raise AssertionError(f"import-time assignment call {name}")


def test_cold_import_has_no_network_socket_subprocess_or_model_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("side effect during cold import")

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "call", boom)
    sys.modules.pop(MODULE_NAME, None)
    module = importlib.import_module(MODULE_NAME)
    assert module.IMPORT_SIDE_EFFECTS_PERFORMED is False
    assert module.IMPORT_SCAN_PERFORMED is False
    assert callable(module.record_python_execution_trace)
    for banned in ("torch", "transformers", "requests", "urllib3", "httpx", "duckdb"):
        assert banned not in sys.modules


def test_call_and_return_events_bind_exact_code_environment_and_source() -> None:
    env = {"language": "python", "python_version": "3.12.3", "python_implementation": "cpython"}
    record = record_python_execution_trace(
        ping,
        environment_binding=env,
        tree_cid=None,
    )
    assert record.accepted_transition is True
    assert record.status == "collected"
    kinds = _kinds(record)
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    names = {event.logical_name for event in record.events}
    assert any(name.endswith("ping") for name in names)
    assert any(name.endswith("pong") for name in names)
    for event in record.events:
        assert event.tree_cid == record.tree_cid
        assert event.source_cid == record.source_cid
        assert event.environment_binding_cid == record.environment_binding_cid
        assert event.language == "python"
        assert "timestamp" not in event.to_dict()
        assert "wall_clock" not in event.to_dict()
        assert event.event_origin == "observed"
    other = record_python_execution_trace(
        ping,
        environment_binding={"language": "python", "python_version": "3.11.0"},
    )
    assert other.environment_binding_cid != record.environment_binding_cid
    assert other.trace.execution_trace_cid != record.trace.execution_trace_cid
    retargeted = record_python_execution_trace(
        ping,
        environment_binding=env,
        tree_cid=cid_for_bytes(b"tree:other-binding"),
    )
    assert retargeted.tree_cid != record.tree_cid
    assert retargeted.events[0].program_event_cid != record.events[0].program_event_cid


def test_exception_and_handler_events_are_collected() -> None:
    record = record_python_execution_trace(handled)
    kinds = set(_kinds(record))
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    raised = [event for event in record.events if event.event_kind == EventKind.RAISE.value]
    assert raised
    assert raised[0].exception_snapshot_cid is not None
    caught = [
        event
        for event in record.events
        if event.event_kind in {EventKind.CATCH.value, EventKind.HANDLER.value}
    ]
    assert caught
    assert any(event.handler_state_cid is not None for event in caught)
    failed = record_python_execution_trace(unhandled)
    assert failed.result_kind == "exception"
    assert failed.exception_type == "KeyError"
    assert EventKind.RAISE.value in _kinds(failed)


def test_yield_and_await_events_are_collected() -> None:
    generated = record_python_execution_trace(producer)
    assert EventKind.YIELD.value in _kinds(generated)
    awaited = record_python_execution_trace(outer_async)
    kinds = set(_kinds(awaited))
    assert EventKind.CALL.value in kinds
    assert EventKind.AWAIT.value in kinds or EventKind.RETURN.value in kinds
    assert awaited.accepted_transition is True
    names = {event.logical_name for event in awaited.events}
    assert any("outer_async" in name or "inner_async" in name for name in names)


def test_payload_bounds_and_secret_redaction() -> None:
    policy = TraceCollectionPolicy(
        capture_locals=True,
        max_payload_bytes=2_048,
        max_summary_chars=64,
        max_summary_keys=8,
    )
    private = record_python_execution_trace(
        secret_holder,
        policy=policy,
        include_raw_bodies=True,
        privacy_class=PrivacyClass.PRIVATE,
    )
    public = private.public_record()
    assert public.includes_raw_bodies is False
    assert public.privacy_class == PrivacyClass.PUBLIC.value
    assert public.trace.includes_raw_bodies is False
    assert public.trace.raw_execution_state_cids == ()
    dumped = json.dumps(public.to_dict())
    assert "s3cret" not in dumped
    assert "password" not in dumped
    assert public.to_dict()["includes_raw_bodies"] is False
    with pytest.raises(PythonExecutionTraceError, match="remain private"):
        record_python_execution_trace(
            secret_holder,
            include_raw_bodies=True,
            privacy_class=PrivacyClass.PUBLIC,
        )
    bounded = record_python_execution_trace(
        bulky,
        policy=policy,
        include_raw_bodies=True,
        privacy_class=PrivacyClass.PRIVATE,
    )
    for state in bounded.states:
        encoded = json.dumps(state.to_dict())
        assert len(encoded) < 20_000
        assert "Q" * 1_000 not in encoded
    redactor = TraceRedactor(max_payload_bytes=256, max_summary_chars=8, max_summary_keys=2)
    payload, redacted = redactor.redact_mapping(
        {"password": "s3cret", "locals": {"x": 1, "y": 2, "z": 3}, "blob": "Z" * 5_000}
    )
    assert "password" not in payload
    assert "secrets" in redacted or "blob" in redacted or "payload" in redacted or "keys" in redacted
    encoded = json.dumps(payload)
    assert "s3cret" not in encoded
    assert len(encoded) <= 512


def test_network_subprocess_and_database_are_denied_during_collection() -> None:
    def probe_network() -> None:
        socket.create_connection(("127.0.0.1", 1))

    record = record_python_execution_trace(probe_network)
    assert record.accepted_transition is False
    assert record.status in {"isolated", "cancelled", "collected"}
    kinds = _kinds(record)
    assert EventKind.EXTERNAL.value in kinds or record.result_kind == "isolated"
    external = [event for event in record.events if event.event_kind == EventKind.EXTERNAL.value]
    if external:
        payload = dict(external[0].payload)
        assert payload.get("denied") is True
        assert payload.get("channel") in {"network", "external"}
    assert record.replay_promised is False

    def probe_subprocess() -> None:
        subprocess.run(["true"], check=False)

    blocked = record_python_execution_trace(probe_subprocess)
    assert blocked.accepted_transition is False
    assert blocked.result_kind in {"isolated", "exception", "cancelled"}


def test_cancellation_emits_no_accepted_transition() -> None:
    token = TraceCancellation("requested")
    token.cancel("requested")
    skipped = record_python_execution_trace(ping, cancellation=token)
    assert skipped.status == "cancelled"
    assert skipped.accepted_transition is False
    assert skipped.cancellation is not None
    assert skipped.cancellation.accepted_transition is False
    assert skipped.replay_promised is False
    assert EventKind.UNAVAILABLE.value in _kinds(skipped)
    with pytest.raises(PythonExecutionTraceError, match="accepted transition"):
        replay_deterministic_trace(skipped, subject=ping)

    bounded = record_python_execution_trace(
        producer,
        policy=TraceCollectionPolicy(max_events=2, max_line_events=1),
    )
    assert bounded.status == "cancelled"
    assert bounded.accepted_transition is False
    assert bounded.cancellation is not None
    assert bounded.cancellation.accepted_transition is False
    assert "accepted_transition" in bounded.cancellation.to_dict()
    assert bounded.cancellation.to_dict()["accepted_transition"] is False
    public = bounded.to_dict()
    assert public["accepted_transition"] is False
    with pytest.raises(PythonExecutionTraceError, match="accepted_transition"):
        TraceCancellation.from_dict(
            {**token.to_dict(), "cancelled": True, "accepted_transition": True}
        )


def test_deterministic_promised_replay_matches_and_bindings_fail_closed() -> None:
    env = {"language": "python", "python_version": "3.12.3"}
    first = record_python_execution_trace(ping, environment_binding=env)
    assert first.replay_promised is True
    assert first.accepted_transition is True
    replayed = replay_deterministic_trace(first, subject=ping)
    assert replayed.matched is True
    assert replayed.original_trace_cid == replayed.replay_trace_cid
    assert replayed.original_event_cids == replayed.replay_event_cids
    assert replayed.accepted_transition is True
    again = record_python_execution_trace(ping, environment_binding=env)
    assert again.trace.execution_trace_cid == first.trace.execution_trace_cid
    assert tuple(again.trace.event_cids) == tuple(first.trace.event_cids)

    def other() -> int:
        return 2

    with pytest.raises(PythonExecutionTraceError, match="code_cid"):
        replay_deterministic_trace(first, subject=other)
    isolated = record_python_execution_trace(
        lambda: socket.create_connection(("127.0.0.1", 1))
    )
    assert isolated.replay_promised is False
    with pytest.raises(PythonExecutionTraceError, match="not promised"):
        replay_deterministic_trace(isolated, subject=ping)


def test_private_raw_bodies_never_enter_public_records() -> None:
    private = record_python_execution_trace(
        secret_holder,
        policy=TraceCollectionPolicy(capture_locals=True),
        include_raw_bodies=True,
        privacy_class=PrivacyClass.PRIVATE,
    )
    assert private.includes_raw_bodies is True
    public = private.public_record()
    assert public.includes_raw_bodies is False
    assert public.states == ()
    assert public.trace.includes_raw_bodies is False
    assert public.trace.privacy_class == PrivacyClass.PUBLIC.value
    blob = json.dumps(private.to_dict())
    assert '"includes_raw_bodies":false' in blob.replace(" ", "")
    assert "s3cret" not in blob
    assert private.to_dict()["privacy_class"] == PrivacyClass.PUBLIC.value
    assert public.trace.completeness_claim != CompletenessClaim.FULL_STATE.value
    assert "raw_body" in public.trace.redacted_dimensions


def test_unsupported_language_and_unknown_policy_fields_fail_closed() -> None:
    with pytest.raises(PythonExecutionTraceError, match="typed unavailable"):
        TraceCollectionPolicy(language="javascript")
    with pytest.raises(PythonExecutionTraceError, match="unknown"):
        TraceCollectionPolicy.from_dict(
            {**TraceCollectionPolicy().to_dict(), "shell": True}
        )
    with pytest.raises(PythonExecutionTraceError, match="callable"):
        record_python_execution_trace(1)  # type: ignore[arg-type]


def test_line_events_are_policy_bounded() -> None:
    record = record_python_execution_trace(
        ping,
        policy=TraceCollectionPolicy(collect_lines=True, max_line_events=1, max_events=64),
    )
    line_events = [event for event in record.events if event.event_kind == EventKind.LINE.value]
    assert len(line_events) <= 1
    assert EventKind.CALL.value in _kinds(record)


def test_tracer_record_method_matches_module_function() -> None:
    env = {"language": "python", "python_version": "3.12.3"}
    policy = TraceCollectionPolicy(collect_lines=False)
    tracer = PythonExecutionTracer(policy)
    via_class = tracer.record(ping, environment_binding=env)
    via_function = record_python_execution_trace(
        ping, policy=policy, environment_binding=env
    )
    assert via_class.trace.execution_trace_cid == via_function.trace.execution_trace_cid
    assert EventKind.LINE.value not in _kinds(via_class)
    assert EventKind.CALL.value in _kinds(via_class)

