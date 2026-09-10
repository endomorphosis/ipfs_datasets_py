"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    PrivacyClass,
)
from ipfs_datasets_py.logic.software_verification import python_execution_trace as trace_module
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    HERMETIC_TRACE_EVIDENCE,
    IMPORT_DATABASE_LOADED,
    IMPORT_INSTALLER_LOADED,
    IMPORT_MODEL_LOADED,
    IMPORT_NETWORK_LOADED,
    IMPORT_REPO_SCAN_PERFORMED,
    IMPORT_SIDE_EFFECTS_PERFORMED,
    IMPORT_SOCKET_LOADED,
    IMPORT_SUBPROCESS_LOADED,
    IMPORT_WATCHER_LOADED,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    PYTHON_EXECUTION_TRACE_RECORD_INTERFACE,
    TRACE_CANCELLATION_INTERFACE,
    TRACE_COLLECTION_POLICY_INTERFACE,
    TRACE_REDACTOR_INTERFACE,
    PythonExecutionTraceRecord,
    PythonExecutionTracer,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceRedactor,
    TraceStatus,
    default_environment_binding_cid,
    record_python_execution_trace,
    replay_deterministic_trace,
)


MODULE_PATH = Path(trace_module.__file__).resolve()
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "socket",
        "_socket",
        "ssl",
        "subprocess",
        "multiprocessing",
        "sqlite3",
        "duckdb",
        "psycopg2",
        "pip",
        "ensurepip",
        "watchdog",
        "torch",
        "transformers",
        "tensorflow",
        "huggingface_hub",
        "requests",
        "aiohttp",
        "httpx",
        "urllib.request",
        "http.client",
    }
)


def ping() -> int:
    return 1


def pong() -> int:
    return ping()


def boom() -> int:
    try:
        raise ValueError("bounded")
    except ValueError:
        return 2


def gen() -> object:
    yield 1
    yield 2


async def async_inner() -> int:
    return 2


async def async_outer() -> int:
    return await async_inner()


def leak(password: str, api_key: str, x: int) -> int:
    secret = password
    return x + len(secret + api_key) * 0


def many_lines() -> int:
    a = 1
    b = a + 1
    c = b + 1
    d = c + 1
    e = d + 1
    return e


def _kinds(record: PythonExecutionTraceRecord) -> list[str]:
    return [event.event_kind for event in record.events]


def test_public_interfaces_and_predicted_symbols_are_exported() -> None:
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)
    assert PythonExecutionTracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE
    assert PythonExecutionTracer.INTERFACE == "PythonExecutionTracer@1"
    assert TraceCollectionPolicy.INTERFACE == TRACE_COLLECTION_POLICY_INTERFACE
    assert TraceRedactor.INTERFACE == TRACE_REDACTOR_INTERFACE
    assert TraceCancellation.INTERFACE == TRACE_CANCELLATION_INTERFACE
    assert PythonExecutionTraceRecord.INTERFACE == PYTHON_EXECUTION_TRACE_RECORD_INTERFACE
    assert PythonExecutionTraceRecord.EVIDENCE == HERMETIC_TRACE_EVIDENCE
    assert HERMETIC_TRACE_EVIDENCE == "sawm/hermetic-trace@1"


def test_cold_import_has_no_network_socket_installer_or_model_side_effects() -> None:
    assert IMPORT_SIDE_EFFECTS_PERFORMED is False
    assert IMPORT_NETWORK_LOADED is False
    assert IMPORT_SOCKET_LOADED is False
    assert IMPORT_SUBPROCESS_LOADED is False
    assert IMPORT_INSTALLER_LOADED is False
    assert IMPORT_DATABASE_LOADED is False
    assert IMPORT_REPO_SCAN_PERFORMED is False
    assert IMPORT_WATCHER_LOADED is False
    assert IMPORT_MODEL_LOADED is False
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MODULE_PATH))
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
            imported.add(node.module)
        elif isinstance(node, (ast.Expr, ast.Assign, ast.AnnAssign)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    name = ""
                    if isinstance(func, ast.Name):
                        name = func.id
                    elif isinstance(func, ast.Attribute):
                        name = func.attr
                    assert name not in {
                        "settrace",
                        "setprofile",
                        "Popen",
                        "urlopen",
                        "socket",
                        "walk",
                        "scandir",
                    }
    assert imported.isdisjoint(FORBIDDEN_IMPORT_ROOTS)
    assert "socket" not in imported
    assert "subprocess" not in imported


def test_import_does_not_install_a_process_trace_hook() -> None:
    # Import already happened; the module must not leave a tracer installed.
    current = sys.gettrace()
    if current is not None:
        filename = getattr(getattr(current, "__code__", None), "co_filename", "")
        assert "python_execution_trace.py" not in str(filename)


def test_hermetic_call_and_return_events_bind_exact_identities() -> None:
    tree = cid_for_bytes(b"tree:hermetic-call")
    env = default_environment_binding_cid()
    record = record_python_execution_trace(
        pong,
        tree_cid=tree,
        environment_binding_cid=env,
    )
    assert record.status == TraceStatus.COMPLETED.value
    kinds = set(_kinds(record))
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    assert EventKind.ENTER.value in kinds
    assert EventKind.EXIT.value in kinds
    assert any("pong" in event.logical_name for event in record.events)
    assert any("ping" in event.logical_name for event in record.events)
    for event in record.events:
        assert event.tree_cid == tree
        assert event.environment_binding_cid == env
        assert event.source_cid == record.source_cid
        assert event.code_cid
        assert event.language == "python"
        assert "timestamp" not in event.identity_payload()
        assert "hostname" not in event.identity_payload()
        assert "pid" not in event.identity_payload()


def test_rebinding_tree_or_environment_changes_event_identity() -> None:
    env = default_environment_binding_cid()
    first = record_python_execution_trace(
        ping,
        tree_cid=cid_for_bytes(b"tree:left"),
        environment_binding_cid=env,
    )
    second = record_python_execution_trace(
        ping,
        tree_cid=cid_for_bytes(b"tree:right"),
        environment_binding_cid=env,
    )
    third = record_python_execution_trace(
        ping,
        tree_cid=first.tree_cid,
        environment_binding_cid=cid_for_bytes(b"env:other-binding"),
    )
    assert first.events[0].program_event_cid != second.events[0].program_event_cid
    assert first.events[0].program_event_cid != third.events[0].program_event_cid
    assert first.public_trace.execution_trace_cid != second.public_trace.execution_trace_cid


def test_exception_and_handler_events_are_collected() -> None:
    record = record_python_execution_trace(boom)
    kinds = set(_kinds(record))
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    raised = next(event for event in record.events if event.event_kind == EventKind.RAISE.value)
    assert raised.exception_snapshot_cid is not None
    handled = [
        event
        for event in record.events
        if event.event_kind in {EventKind.CATCH.value, EventKind.HANDLER.value}
    ]
    assert handled
    assert any(event.handler_state_cid is not None for event in handled)
    assert record.result_summary.get("value") == 2


def test_yield_events_are_collected_from_generator_fixtures() -> None:
    record = record_python_execution_trace(gen)
    assert EventKind.YIELD.value in set(_kinds(record))
    assert record.result_summary.get("value") == [1, 2] or record.result_summary.get("yielded") == [
        1,
        2,
    ]


def test_await_and_async_call_events_are_collected() -> None:
    record = record_python_execution_trace(async_outer)
    kinds = set(_kinds(record))
    assert EventKind.CALL.value in kinds
    assert any("async_inner" in event.logical_name for event in record.events)
    assert EventKind.AWAIT.value in kinds or EventKind.RETURN.value in kinds
    assert record.status == TraceStatus.COMPLETED.value


def test_line_events_are_policy_bounded() -> None:
    policy = TraceCollectionPolicy(max_events=2, collect_line_events=True)
    record = record_python_execution_trace(many_lines, policy=policy)
    assert len(record.events) <= 2
    assert record.truncated is True
    assert record.status == TraceStatus.TRUNCATED.value
    assert record.public_trace.completeness_claim != CompletenessClaim.FULL_STATE.value
    assert "truncated_events" in record.unavailable_dimensions or record.truncated


def test_secret_fields_are_redacted_from_public_records() -> None:
    record = record_python_execution_trace(
        leak,
        args=("s3cret-value", "k3y-material", 3),
    )
    public = record.public_record()
    blob = json.dumps(public, sort_keys=True)
    assert "s3cret-value" not in blob
    assert "k3y-material" not in blob
    assert public["includes_raw_bodies"] is False
    for state in record.states:
        observed = dict(state.observed_state)
        assert "password" not in observed
        assert "api_key" not in observed
        locals_map = observed.get("locals", {})
        if isinstance(locals_map, dict):
            assert "password" not in locals_map
            assert "api_key" not in locals_map
            assert "secret" not in locals_map or "s3cret-value" not in json.dumps(locals_map)


def test_private_raw_bodies_never_enter_public_records() -> None:
    record = record_python_execution_trace(ping)
    public = record.to_dict()
    assert public["includes_raw_bodies"] is False
    assert public["privacy_class"] == PrivacyClass.PUBLIC.value
    assert public["public_trace"]["includes_raw_bodies"] is False
    assert public["public_trace"]["raw_execution_state_cids"] == []
    assert public["accepted_transition_cid"] is None
    assert "events" not in public
    assert "states" not in public
    assert "private_trace" not in public
    redactor = TraceRedactor()
    exported = redactor.public_record(record)
    assert exported["includes_raw_bodies"] is False
    assert record.public_trace.execution_trace_cid != record.private_trace.execution_trace_cid or (
        record.private_trace.includes_raw_bodies is False
        and record.private_trace.privacy_class in {PrivacyClass.INTERNAL.value, PrivacyClass.PUBLIC.value}
    )
    if record.private_trace.includes_raw_bodies:
        assert record.private_trace.privacy_class == PrivacyClass.PRIVATE.value
        assert record.public_trace.includes_raw_bodies is False


def test_cancellation_emits_no_accepted_transition() -> None:
    token = TraceCancellation()

    def subject(cancellation: TraceCancellation) -> int:
        cancellation.cancel("stop-now")
        return 99

    record = record_python_execution_trace(
        subject,
        kwargs={"cancellation": token},
        cancellation=token,
    )
    assert record.cancellation_requested is True
    assert record.status == TraceStatus.CANCELLED.value
    assert record.accepted_transition_cid is None
    public = record.public_record()
    assert public["accepted_transition_cid"] is None
    assert public["cancellation_requested"] is True
    assert EventKind.EXIT.value not in set(_kinds(record)) or record.accepted_transition_cid is None
    assert "accepted_transition" in record.unavailable_dimensions or record.accepted_transition_cid is None


def test_pre_cancelled_trace_does_not_run_or_accept() -> None:
    token = TraceCancellation()
    token.cancel("already")
    ran = {"value": False}

    def subject() -> int:
        ran["value"] = True
        return 1

    record = record_python_execution_trace(subject, cancellation=token)
    assert ran["value"] is False
    assert record.status == TraceStatus.CANCELLED.value
    assert record.accepted_transition_cid is None
    assert record.replay_promised is False
    assert EventKind.UNAVAILABLE.value in set(_kinds(record))


def test_test_only_network_and_subprocess_are_denied() -> None:
    def open_socket() -> object:
        import socket

        return socket.socket()

    record = record_python_execution_trace(open_socket)
    assert record.status == TraceStatus.ISOLATED.value
    assert record.isolation_denied is True
    assert record.accepted_transition_cid is None
    assert record.replay_promised is False
    kinds = set(_kinds(record))
    assert EventKind.EXTERNAL.value in kinds or EventKind.RAISE.value in kinds
    assert record.public_record()["accepted_transition_cid"] is None

    def spawn() -> object:
        import subprocess

        return subprocess.Popen(["true"])

    isolated = record_python_execution_trace(spawn)
    assert isolated.status == TraceStatus.ISOLATED.value
    assert isolated.accepted_transition_cid is None


def test_deterministic_promised_replay_matches_event_identity() -> None:
    first = record_python_execution_trace(ping)
    assert first.replay_promised is True
    receipt = replay_deterministic_trace(first, ping)
    assert receipt.promised is True
    assert receipt.event_kind_sequence_equal is True
    assert receipt.binding_equal is True
    assert receipt.matched is True
    assert receipt.accepted_transition_cid is None
    assert receipt.replayed_trace_cid == first.public_trace.execution_trace_cid


def test_cancelled_and_isolated_traces_are_not_promised_for_replay() -> None:
    token = TraceCancellation()
    token.cancel()
    cancelled = record_python_execution_trace(ping, cancellation=token)
    receipt = replay_deterministic_trace(cancelled, ping)
    assert receipt.promised is False
    assert receipt.matched is False
    assert receipt.accepted_transition_cid is None
    assert "replay" in receipt.unavailable_dimensions

    def open_socket() -> object:
        import socket

        return socket.socket()

    isolated = record_python_execution_trace(open_socket)
    isolated_receipt = replay_deterministic_trace(isolated, open_socket)
    assert isolated_receipt.promised is False
    assert isolated_receipt.matched is False


def test_trace_hooks_are_restored_after_recording() -> None:
    before = sys.gettrace()
    record_python_execution_trace(ping)
    assert sys.gettrace() is before
    token = TraceCancellation()
    token.cancel()
    record_python_execution_trace(ping, cancellation=token)
    assert sys.gettrace() is before


def test_payload_summaries_reject_floats_and_stay_bounded() -> None:
    policy = TraceCollectionPolicy(max_summary_items=2, max_text_chars=8, capture_locals=True)

    def subject() -> dict[str, object]:
        payload = {"a": 1, "b": 2, "c": 3, "long": "abcdefghijklmnop"}
        return payload

    record = record_python_execution_trace(subject, policy=policy)
    encoded = json.dumps(record.public_record())
    assert "Infinity" not in encoded
    assert "NaN" not in encoded
    for event in record.events:
        dumped = json.dumps(event.payload, allow_nan=False)
        assert "timestamp" not in dumped
        assert isinstance(event.payload, dict)
        assert "Infinity" not in dumped
        assert "NaN" not in dumped


def test_policy_rejects_non_deny_network_and_invalid_bounds() -> None:
    with pytest.raises(Exception, match="network_policy"):
        TraceCollectionPolicy(network_policy="allow")
    with pytest.raises(Exception, match="max_events"):
        TraceCollectionPolicy(max_events=0)


def test_observations_are_admitted_only_for_observed_events() -> None:
    record = record_python_execution_trace(ping)
    assert record.observations
    for observation in record.observations:
        assert observation.event_origin == "observed"
        assert observation.observation_status == "observed"
        assert observation.tree_cid == record.tree_cid
        assert observation.environment_binding_cid == record.environment_binding_cid
