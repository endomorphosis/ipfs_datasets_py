"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import ast
import json
import os
import socket
import sys
import threading
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    PrivacyClass,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    IMPORT_DATABASE_OPENED,
    IMPORT_INSTALLER_INVOKED,
    IMPORT_MODEL_LOADED,
    IMPORT_NETWORK_OPENED,
    IMPORT_REPO_SCAN_PERFORMED,
    IMPORT_SIDE_EFFECTS_PERFORMED,
    IMPORT_SOCKET_OPENED,
    IMPORT_SUBPROCESS_STARTED,
    IMPORT_WATCHER_STARTED,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    PYTHON_EXECUTION_TRACE_RECORD_INTERFACE,
    RECORD_PYTHON_EXECUTION_TRACE_INTERFACE,
    REPLAY_DETERMINISTIC_TRACE_INTERFACE,
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
WORKSPACE_ROOT = Path(__file__).resolve().parents[5]
_SECRET_PASSWORD = "hunter2-secret-value"
_SECRET_KEY = "sk-not-for-public-records"


def _kinds(record) -> list[str]:
    return [str(event.event_kind) for event in record.events]


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _add(left: int, right: int) -> int:
    total = left + right
    return total


def _boom() -> None:
    raise ValueError("bounded")


def _recover() -> str:
    try:
        _boom()
    except ValueError:
        return "ok"
    return "missing"


def _generate() -> int:
    def inner():
        yield 1
        yield 2
        return 3

    iterator = inner()
    first = next(iterator)
    second = next(iterator)
    try:
        next(iterator)
    except StopIteration as stopped:
        return first + second + int(stopped.value or 0)
    return first + second


class _Immediate:
    def __await__(self):
        yield
        return 7


def _await_once() -> int:
    async def inner() -> int:
        value = await _Immediate()
        return value

    coroutine = inner()
    try:
        coroutine.send(None)
        try:
            coroutine.send(None)
        except StopIteration as stopped:
            return int(stopped.value)
    finally:
        coroutine.close()
    raise AssertionError("await fixture did not complete")


def _leaky() -> int:
    password = _SECRET_PASSWORD
    api_key = _SECRET_KEY
    visible = 1
    return visible + len(password) + len(api_key) - len(password) - len(api_key)


def _wide() -> int:
    blob = "x" * 200_000
    return len(blob)


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
    assert TRACE_COLLECTION_POLICY_INTERFACE == "TraceCollectionPolicy@1"
    assert TRACE_REDACTOR_INTERFACE == "TraceRedactor@1"
    assert TRACE_CANCELLATION_INTERFACE == "TraceCancellation@1"
    assert PYTHON_EXECUTION_TRACE_RECORD_INTERFACE == "PythonExecutionTraceRecord@1"
    assert RECORD_PYTHON_EXECUTION_TRACE_INTERFACE == "record_python_execution_trace"
    assert REPLAY_DETERMINISTIC_TRACE_INTERFACE == "replay_deterministic_trace"
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)
    assert PythonExecutionTracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE
    assert TraceCollectionPolicy.INTERFACE == TRACE_COLLECTION_POLICY_INTERFACE
    assert TraceRedactor.INTERFACE == TRACE_REDACTOR_INTERFACE
    assert TraceCancellation.INTERFACE == TRACE_CANCELLATION_INTERFACE


def test_import_sentinels_show_no_forbidden_import_side_effects() -> None:
    assert IMPORT_SIDE_EFFECTS_PERFORMED is False
    assert IMPORT_NETWORK_OPENED is False
    assert IMPORT_SOCKET_OPENED is False
    assert IMPORT_INSTALLER_INVOKED is False
    assert IMPORT_SUBPROCESS_STARTED is False
    assert IMPORT_DATABASE_OPENED is False
    assert IMPORT_REPO_SCAN_PERFORMED is False
    assert IMPORT_WATCHER_STARTED is False
    assert IMPORT_MODEL_LOADED is False


def test_module_ast_has_no_forbidden_import_time_effects() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden_modules = {
        "socket",
        "subprocess",
        "sqlite3",
        "duckdb",
        "watchdog",
        "torch",
        "transformers",
        "urllib",
        "http",
        "requests",
        "pip",
        "venv",
    }
    forbidden_calls = {
        "connect",
        "getaddrinfo",
        "Popen",
        "system",
        "walk",
        "rglob",
        "scandir",
        "load_model",
        "from_pretrained",
    }
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
        elif isinstance(node, (ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                name = ""
                if isinstance(child.func, ast.Name):
                    name = child.func.id
                elif isinstance(child.func, ast.Attribute):
                    name = child.func.attr
                if name in forbidden_calls:
                    raise AssertionError(f"forbidden import-time call: {name}")
    assert not (imported & forbidden_modules), imported & forbidden_modules


def test_cold_import_probe_denies_network_socket_subprocess_and_watchers() -> None:
    script = r"""
import json
import os
import sys
import threading

effects = []

def forbidden(name):
    def call(*args, **kwargs):
        effects.append(name)
        raise AssertionError("forbidden import side effect: " + name)
    return call

os.system = forbidden("os.system")
_orig_thread_start = threading.Thread.start

def _thread_start(self, *args, **kwargs):
    effects.append("threading.Thread.start")
    raise AssertionError("forbidden import side effect: threading.Thread.start")

threading.Thread.start = _thread_start

def audit(event, args):
    if event in {
        "socket.connect",
        "socket.getaddrinfo",
        "subprocess.Popen",
        "os.system",
        "sqlite3.connect",
    }:
        effects.append(event)
        raise AssertionError("forbidden import side effect: " + event)

sys.addaudithook(audit)
import ipfs_datasets_py.logic.software_verification.python_execution_trace as mod
assert mod.IMPORT_SIDE_EFFECTS_PERFORMED is False
assert not effects, effects
print(json.dumps({"ok": True}, sort_keys=True))
"""
    environment = dict(os.environ)
    environment["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = "1"
    environment["IPFS_DATASETS_AUTO_INSTALL"] = "0"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    pythonpath = os.pathsep.join(
        [
            str(WORKSPACE_ROOT / "ipfs_datasets_py"),
            str(WORKSPACE_ROOT / "ipfs_kit_py"),
            str(WORKSPACE_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    environment["PYTHONPATH"] = pythonpath
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(WORKSPACE_ROOT),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True}


def test_call_and_return_events_bind_exact_code_and_environment() -> None:
    tree_cid = cid_for_bytes(b"tree:python-execution-trace-v1")
    policy = TraceCollectionPolicy(
        tree_cid=tree_cid,
        environment_binding={"language": "python", "python_version": "3.12.0"},
        max_line_events=64,
    )
    record = record_python_execution_trace(_add, 2, 3, policy=policy)
    assert record.accepted_transition is None
    assert record.cancelled is False
    assert record.outcome == "returned"
    kinds = set(_kinds(record))
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    assert record.tree_cid == tree_cid
    assert record.environment_binding_cid == record.events[0].environment_binding_cid
    for event in record.events:
        assert event.tree_cid == tree_cid
        assert event.source_cid == record.source_cid
        assert event.environment_binding_cid == record.environment_binding_cid
        assert event.subject_cid == record.subject_cid
        assert event.code_cid
        assert event.logical_name
    assert record.trace.tree_cid == tree_cid
    assert record.capture_profile_cid == policy.capture_profile_cid


def test_exception_and_handler_events_are_collected() -> None:
    record = record_python_execution_trace(_recover)
    kinds = set(_kinds(record))
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    raised = next(event for event in record.events if event.event_kind == EventKind.RAISE.value)
    assert raised.exception_snapshot_cid
    assert raised.stack_frame_cids
    handled = [
        event
        for event in record.events
        if event.event_kind in {EventKind.CATCH.value, EventKind.HANDLER.value}
    ]
    assert handled
    assert any(event.handler_state_cid for event in handled)
    assert record.accepted_transition is None


def test_yield_and_await_events_are_collected() -> None:
    yielded = record_python_execution_trace(_generate)
    assert EventKind.YIELD.value in set(_kinds(yielded))
    awaited = record_python_execution_trace(_await_once)
    kinds = set(_kinds(awaited))
    assert EventKind.AWAIT.value in kinds or EventKind.YIELD.value in kinds
    assert awaited.accepted_transition is None


def test_payload_bounds_are_enforced() -> None:
    policy = TraceCollectionPolicy(max_text_chars=32, max_summary_items=4, max_line_events=32)
    record = record_python_execution_trace(_wide, policy=policy)
    encoded = _dump(record.public_record())
    assert "x" * 200_000 not in encoded
    for event in record.events:
        payload = event.canonical_bytes()
        assert len(payload) < 16_384
    for frame in record.frames:
        dumped = _dump(frame.to_dict())
        assert "x" * 200_000 not in dumped
        assert len(dumped) < 20_000


def test_secrets_are_redacted_from_summaries_and_public_records() -> None:
    policy = TraceCollectionPolicy(
        include_raw_bodies=True,
        privacy_class=PrivacyClass.PRIVATE,
        max_line_events=64,
    )
    record = record_python_execution_trace(_leaky, policy=policy)
    public = record.public_record()
    private = record.trace.to_dict()
    frame_payloads = [frame.to_dict() for frame in record.frames]
    for blob in (_dump(public), _dump(private), _dump(frame_payloads)):
        assert _SECRET_PASSWORD not in blob
        assert _SECRET_KEY not in blob
    for frame in record.frames:
        locals_map = dict(frame.state_summary.get("locals") or {})
        assert "password" not in locals_map
        assert "api_key" not in locals_map
    assert {"api_key", "password"} <= set(record.redaction_profile.redacted_dimensions)
    assert record.trace.completeness_claim != CompletenessClaim.FULL_STATE.value
    assert public["includes_raw_bodies"] is False


def test_network_is_denied_during_hermetic_collection() -> None:
    def probe() -> None:
        probe_socket = socket.socket()
        try:
            probe_socket.connect(("127.0.0.1", 1))
        finally:
            probe_socket.close()

    record = record_python_execution_trace(probe)
    assert record.accepted_transition is None
    kinds = set(_kinds(record))
    assert EventKind.EXTERNAL.value in kinds or record.cancelled is True
    if EventKind.EXTERNAL.value in kinds:
        external = next(
            event for event in record.events if event.event_kind == EventKind.EXTERNAL.value
        )
        assert external.payload.get("denied") is True
        assert external.payload.get("external_event") == "socket.connect"
    assert record.cancelled is True or record.outcome in {"denied", "cancelled", "raised"}


def test_cancellation_emits_no_accepted_transition() -> None:
    def stop() -> None:
        raise TraceCancellation("operator-stop")

    cancelled = record_python_execution_trace(stop)
    assert cancelled.cancelled is True
    assert cancelled.accepted_transition is None
    assert cancelled.cancellation is not None
    assert cancelled.cancellation.accepted_transition is None
    assert cancelled.trace.completeness_claim != CompletenessClaim.FULL_STATE.value
    bounded = TraceCollectionPolicy(max_events=2, max_line_events=64)
    def many() -> int:
        total = 0
        total += 1
        total += 2
        total += 3
        total += 4
        return total

    truncated = record_python_execution_trace(many, policy=bounded)
    assert truncated.accepted_transition is None
    assert truncated.cancelled is True
    assert truncated.cancellation is not None
    assert truncated.cancellation.reason == "max_events"


def test_private_raw_bodies_never_enter_public_records() -> None:
    policy = TraceCollectionPolicy(
        include_raw_bodies=True,
        privacy_class=PrivacyClass.PRIVATE,
        max_line_events=32,
    )
    record = record_python_execution_trace(_add, 4, 5, policy=policy)
    assert record.trace.includes_raw_bodies is True
    assert record.trace.privacy_class == PrivacyClass.PRIVATE.value
    assert record.public_trace.includes_raw_bodies is False
    assert record.public_trace.raw_execution_state_cids == ()
    assert record.public_trace.privacy_class == PrivacyClass.PUBLIC.value
    public = record.public_record()
    assert public["includes_raw_bodies"] is False
    assert public["raw_execution_state_cids"] == []
    assert public["accepted_transition"] is None
    assert public["trace"]["includes_raw_bodies"] is False
    with pytest.raises(PythonExecutionTraceError, match="public privacy class"):
        TraceCollectionPolicy(include_raw_bodies=True, privacy_class=PrivacyClass.PUBLIC)


def test_deterministic_promised_replay_preserves_identity() -> None:
    policy = TraceCollectionPolicy(
        tree_cid=cid_for_bytes(b"tree:replay"),
        environment_binding={"language": "python", "python_version": "3.12.0"},
        max_line_events=32,
    )
    first = record_python_execution_trace(_add, 8, 13, policy=policy)
    second = record_python_execution_trace(_add, 8, 13, policy=policy)
    assert first.trace.execution_trace_cid == second.trace.execution_trace_cid
    assert first.public_trace.execution_trace_cid == second.public_trace.execution_trace_cid
    replayed = replay_deterministic_trace(first)
    assert replayed.trace.execution_trace_cid == first.trace.execution_trace_cid
    assert replayed.public_trace.execution_trace_cid == first.public_trace.execution_trace_cid
    assert replayed.accepted_transition is None
    assert replayed.cancelled is False


def test_replay_of_cancelled_trace_still_has_no_accepted_transition() -> None:
    def stop() -> None:
        raise TraceCancellation("replay-cancel")

    original = record_python_execution_trace(stop)
    replayed = replay_deterministic_trace(original)
    assert replayed.cancelled is True
    assert replayed.accepted_transition is None
    assert replayed.trace.execution_trace_cid == original.trace.execution_trace_cid


def test_external_nondeterminism_is_explicit_or_unavailable() -> None:
    def probe() -> str:
        return "pure"

    record = record_python_execution_trace(probe)
    if EventKind.EXTERNAL.value in set(_kinds(record)):
        external = [
            event for event in record.events if event.event_kind == EventKind.EXTERNAL.value
        ]
        assert external
        assert all(event.payload.get("external_event") for event in external)
    else:
        assert "heap" in record.trace.unavailable_dimensions
    assert record.trace.completeness_claim != CompletenessClaim.FULL_STATE.value


def test_repeated_recordings_do_not_scan_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("repository scan is forbidden during tracing")

    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(os, "scandir", boom)
    monkeypatch.setattr(Path, "rglob", boom)
    monkeypatch.setattr(Path, "glob", boom)
    record = record_python_execution_trace(_add, 1, 1)
    assert record.events
    assert record.accepted_transition is None


def test_tracer_does_not_start_watchers_or_threads() -> None:
    started: list[str] = []
    original = threading.Thread.start

    def wrapped(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        started.append("thread")
        return original(self, *args, **kwargs)

    threading.Thread.start = wrapped  # type: ignore[method-assign]
    try:
        record = record_python_execution_trace(_add, 1, 2)
    finally:
        threading.Thread.start = original  # type: ignore[method-assign]
    assert not started
    assert record.events


def test_redactor_public_record_rejects_raw_bodies() -> None:
    policy = TraceCollectionPolicy(
        include_raw_bodies=True,
        privacy_class=PrivacyClass.PRIVATE,
    )
    record = record_python_execution_trace(_add, 1, 1, policy=policy)
    public = TraceRedactor(policy).public_record(record)
    assert public["includes_raw_bodies"] is False
    assert cid_for_structured(public["trace"])
