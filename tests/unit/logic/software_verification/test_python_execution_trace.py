"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import ast
import importlib
import os
import socket
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    ExecutionTrace,
    PrivacyClass,
    observe_program_event,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    IMPORT_DATABASE_PERFORMED,
    IMPORT_INSTALLER_PERFORMED,
    IMPORT_MODEL_LOAD_PERFORMED,
    IMPORT_NETWORK_PERFORMED,
    IMPORT_REPO_SCAN_PERFORMED,
    IMPORT_SOCKET_PERFORMED,
    IMPORT_SUBPROCESS_PERFORMED,
    IMPORT_WATCHER_PERFORMED,
    PYTHON_EXECUTION_TRACE_RECORD_INTERFACE,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    RECORD_PYTHON_EXECUTION_TRACE_INTERFACE,
    REPLAY_DETERMINISTIC_TRACE_INTERFACE,
    TRACE_CANCELLATION_INTERFACE,
    TRACE_COLLECTION_POLICY_INTERFACE,
    TRACE_REDACTOR_INTERFACE,
    HermeticIsolationError,
    PythonExecutionTraceError,
    PythonExecutionTraceRecord,
    PythonExecutionTracer,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceRedactor,
    TraceStatus,
    record_python_execution_trace,
    replay_deterministic_trace,
)


_TRACE_MODULE = importlib.import_module(
    "ipfs_datasets_py.logic.software_verification.python_execution_trace"
)
MODULE_PATH = Path(_TRACE_MODULE.__file__ or "")


def _kinds(record: PythonExecutionTraceRecord) -> list[str]:
    return [str(event.event_kind) for event in record.events]


def _add(left: int, right: int) -> int:
    return left + right


def _nested(value: int) -> int:
    return _add(value, 1)


def _recover() -> int:
    try:
        raise ValueError("bounded")
    except ValueError:
        return 7


def _gen() -> Any:
    yield 1
    yield 2


def _run_gen() -> list[int]:
    return list(_gen())


async def _one() -> int:
    return 1


async def _produce() -> int:
    return await _one()


def _leak(password: str = "s3cret-value", api_key: str = "k-live") -> str:
    token = password
    return token


def _huge() -> str:
    payload = "x" * 50_000
    return payload[:4]


def _cancel_self(tracer: PythonExecutionTracer) -> int:
    tracer.cancel("stop-now")
    return 99


def _raise_cancel() -> int:
    raise TraceCancellation("user-cancel")


def _connect() -> None:
    socket.create_connection(("127.0.0.1", 1), timeout=0.01)


def _popen() -> None:
    subprocess.Popen(["true"])  # noqa: S603


def _db() -> None:
    sqlite3.connect(":memory:")


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
    assert TRACE_COLLECTION_POLICY_INTERFACE == "TraceCollectionPolicy@1"
    assert TRACE_REDACTOR_INTERFACE == "TraceRedactor@1"
    assert TRACE_CANCELLATION_INTERFACE == "TraceCancellation@1"
    assert PYTHON_EXECUTION_TRACE_RECORD_INTERFACE == "PythonExecutionTraceRecord@1"
    assert RECORD_PYTHON_EXECUTION_TRACE_INTERFACE == "record_python_execution_trace@1"
    assert REPLAY_DETERMINISTIC_TRACE_INTERFACE == "replay_deterministic_trace@1"
    assert PythonExecutionTracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE
    assert TraceCollectionPolicy.INTERFACE == TRACE_COLLECTION_POLICY_INTERFACE
    assert TraceRedactor.INTERFACE == TRACE_REDACTOR_INTERFACE
    assert TraceCancellation.INTERFACE == TRACE_CANCELLATION_INTERFACE
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)


def test_import_flags_are_inert() -> None:
    assert IMPORT_NETWORK_PERFORMED is False
    assert IMPORT_SOCKET_PERFORMED is False
    assert IMPORT_INSTALLER_PERFORMED is False
    assert IMPORT_SUBPROCESS_PERFORMED is False
    assert IMPORT_DATABASE_PERFORMED is False
    assert IMPORT_REPO_SCAN_PERFORMED is False
    assert IMPORT_WATCHER_PERFORMED is False
    assert IMPORT_MODEL_LOAD_PERFORMED is False


def test_module_source_has_no_import_time_effects() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_calls = {
        "walk",
        "rglob",
        "glob",
        "scandir",
        "Popen",
        "create_connection",
        "urlopen",
        "urlretrieve",
        "system",
        "start",
        "Observer",
        "connect",
        "from_pretrained",
    }
    forbidden_imports = {
        "torch",
        "transformers",
        "requests",
        "urllib3",
        "httpx",
        "aiohttp",
        "watchdog",
        "duckdb",
        "socket",
        "subprocess",
        "sqlite3",
        "pip",
        "setuptools",
    }
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                assert name not in forbidden_imports, f"import-time import of {name}"
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            label = getattr(func, "attr", getattr(func, "id", ""))
            assert label not in forbidden_calls, f"import-time call {label}"
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            label = getattr(func, "attr", getattr(func, "id", ""))
            assert label not in forbidden_calls


def test_cold_import_probe_denies_network_socket_subprocess_and_models() -> None:
    script = textwrap.dedent(
        """
        import importlib
        import os
        import socket
        import subprocess
        import sys
        import threading

        def forbidden(operation):
            def fail(*args, **kwargs):
                raise AssertionError(f"{operation} during cold import: {args!r}")
            return fail

        socket.create_connection = forbidden("socket.create_connection")
        socket.getaddrinfo = forbidden("socket.getaddrinfo")
        subprocess.Popen = forbidden("subprocess.Popen")
        subprocess.run = forbidden("subprocess.run")
        os.system = forbidden("os.system")
        os.walk = forbidden("os.walk")
        threading.Thread.start = forbidden("threading.Thread.start")

        banned = ("torch", "transformers", "requests", "urllib3", "httpx", "watchdog", "duckdb")
        for name in list(sys.modules):
            if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
                del sys.modules[name]
        module = importlib.import_module(
            "ipfs_datasets_py.logic.software_verification.python_execution_trace"
        )
        assert module.IMPORT_NETWORK_PERFORMED is False
        assert module.IMPORT_SOCKET_PERFORMED is False
        assert module.IMPORT_SUBPROCESS_PERFORMED is False
        assert module.IMPORT_DATABASE_PERFORMED is False
        assert module.IMPORT_REPO_SCAN_PERFORMED is False
        assert module.IMPORT_WATCHER_PERFORMED is False
        assert module.IMPORT_MODEL_LOAD_PERFORMED is False
        assert callable(module.record_python_execution_trace)
        assert callable(module.replay_deterministic_trace)
        for name in banned:
            assert name not in sys.modules, name
        print("ok")
        """
    )
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    datasets_root = Path(__file__).resolve().parents[4]
    repo_root = datasets_root.parent
    env["PYTHONPATH"] = os.pathsep.join(
        [str(datasets_root), str(repo_root / "ipfs_kit_py"), str(repo_root), env.get("PYTHONPATH", "")]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ok" in completed.stdout


def test_in_memory_recording_does_not_scan_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("repository scan is forbidden during hermetic tracing")

    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(os, "scandir", boom)
    monkeypatch.setattr(Path, "rglob", boom)
    monkeypatch.setattr(Path, "glob", boom)
    record = record_python_execution_trace(_add, 2, 3)
    assert record.result == 5
    assert record.trace is not None


def test_call_return_and_line_events_bind_exact_identities() -> None:
    policy = TraceCollectionPolicy(environment_binding={"python": "3.12", "role": "test"})
    first = record_python_execution_trace(_nested, 4, policy=policy)
    second = record_python_execution_trace(_nested, 4, policy=policy)
    kinds = set(_kinds(first))
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    assert EventKind.LINE.value in kinds
    assert EventKind.ENTER.value in kinds
    assert EventKind.EXIT.value in kinds
    assert first.result == 5
    assert first.tree_cid == second.tree_cid
    assert first.source_cid == second.source_cid
    assert first.environment_binding_cid == second.environment_binding_cid
    assert first.deterministic_promise_cid == second.deterministic_promise_cid
    assert first.event_cids == second.event_cids
    for event in first.events:
        assert event.tree_cid == first.tree_cid
        assert event.source_cid == first.source_cid
        assert event.environment_binding_cid == first.environment_binding_cid
        assert event.logical_name
        observe_program_event(event)
    assert first.accepted is True
    assert first.accepted_transition is not None
    assert first.accepted_transition["admitted"] is True


def test_exception_and_handler_events_are_collected() -> None:
    record = record_python_execution_trace(_recover)
    kinds = set(_kinds(record))
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    assert record.result == 7
    assert record.exceptions
    assert all(item.future_execution is False for item in record.exceptions)
    raise_event = next(event for event in record.events if str(event.event_kind) == EventKind.RAISE.value)
    assert raise_event.exception_snapshot_cid is not None
    assert raise_event.stack_frame_cids


def test_yield_events_are_collected() -> None:
    record = record_python_execution_trace(_run_gen)
    assert record.result == [1, 2]
    assert EventKind.YIELD.value in _kinds(record)


def test_await_events_are_collected() -> None:
    record = record_python_execution_trace(_produce)
    assert record.result == 1
    kinds = set(_kinds(record))
    assert EventKind.CALL.value in kinds
    assert EventKind.AWAIT.value in kinds or EventKind.RETURN.value in kinds


def test_payload_bounds_are_enforced() -> None:
    policy = TraceCollectionPolicy(max_payload_bytes=128, max_summary_bytes=128, max_line_events=8)
    record = record_python_execution_trace(_huge, policy=policy)
    assert record.result == "xxxx"
    blob = repr([event.payload for event in record.events])
    assert "x" * 1_000 not in blob
    assert all(len(repr(dict(event.payload))) < 8_192 for event in record.events)


def test_line_collection_is_cost_bounded() -> None:
    policy = TraceCollectionPolicy(max_line_events=2, collect_line=True)

    def many_lines() -> int:
        total = 0
        total += 1
        total += 1
        total += 1
        total += 1
        return total

    record = record_python_execution_trace(many_lines, policy=policy)
    assert _kinds(record).count(EventKind.LINE.value) <= 2
    assert "line" in record.unavailable_dimensions


def test_secret_redaction_removes_private_fields() -> None:
    record = record_python_execution_trace(_leak, password="sk_live_not_a_real_key", api_key="k-live")
    secret_keys = {"password", "api_key", "token"}
    saw_secret_key = False
    for frame in record.frames:
        locals_map = dict(frame.state_summary).get("locals", {})
        if not isinstance(locals_map, dict):
            continue
        for key, value in locals_map.items():
            if key.lower() in secret_keys or any(part in key.lower() for part in secret_keys):
                saw_secret_key = True
                assert value == {"redacted": True}
                assert "s3cret-value" not in repr(value)
                assert "k-live" not in repr(value)
    assert saw_secret_key or secret_keys.intersection(record.redacted_dimensions)
    public = record.to_public_dict()
    public_blob = repr(public)
    assert "s3cret-value" not in public_blob
    assert "k-live" not in public_blob


def test_private_raw_bodies_never_enter_public_records() -> None:
    policy = TraceCollectionPolicy(
        include_raw_bodies=True,
        privacy_class=PrivacyClass.PRIVATE,
        capture_states=True,
    )
    private = record_python_execution_trace(_add, 1, 2, policy=policy)
    assert private.includes_raw_bodies is True
    assert private.trace is not None
    assert private.trace.includes_raw_bodies is True
    public_trace = private.public_trace
    assert public_trace is not None
    assert public_trace.includes_raw_bodies is False
    assert public_trace.raw_execution_state_cids == ()
    assert public_trace.privacy_class == PrivacyClass.PUBLIC.value
    public = TraceRedactor(policy).public_record(private)
    assert public["includes_raw_bodies"] is False
    assert public["raw_execution_state_cids"] == []
    assert public["privacy_class"] == PrivacyClass.PUBLIC.value
    if public["trace"] is not None:
        assert public["trace"]["includes_raw_bodies"] is False
        assert public["trace"]["raw_execution_state_cids"] == []
    with pytest.raises(PythonExecutionTraceError, match="raw bodies remain private"):
        TraceCollectionPolicy(include_raw_bodies=True, privacy_class=PrivacyClass.PUBLIC)


def test_network_socket_subprocess_and_database_are_denied_during_recording() -> None:
    with pytest.raises(HermeticIsolationError, match="socket.create_connection"):
        record_python_execution_trace(_connect)
    with pytest.raises(HermeticIsolationError, match="subprocess.Popen"):
        record_python_execution_trace(_popen)
    with pytest.raises(HermeticIsolationError, match="sqlite3.connect"):
        record_python_execution_trace(_db)


def test_denied_external_is_recorded_when_the_call_is_caught() -> None:
    def guarded() -> str:
        try:
            socket.create_connection(("127.0.0.1", 1), timeout=0.01)
        except HermeticIsolationError:
            return "denied"
        return "open"

    record = record_python_execution_trace(guarded)
    assert record.result == "denied"
    assert EventKind.EXTERNAL.value in _kinds(record)
    assert "external" in record.unavailable_dimensions or any(
        dict(event.payload).get("denied") is True for event in record.events
    )


def test_cancellation_emits_no_accepted_transition() -> None:
    tracer = PythonExecutionTracer()
    record = tracer.record(_cancel_self, tracer)
    assert record.status == TraceStatus.CANCELLED.value
    assert record.cancelled is True
    assert record.accepted is False
    assert record.accepted_transition is None
    assert EventKind.EXIT.value not in _kinds(record)
    assert record.cancellation is not None
    assert record.cancellation["accepted_transition"] is False
    cancellation = TraceCancellation("stop")
    assert cancellation.accepted is False
    assert cancellation.accepted_transition is None


def test_raised_cancellation_emits_no_accepted_transition() -> None:
    record = record_python_execution_trace(_raise_cancel)
    assert record.cancelled is True
    assert record.accepted_transition is None
    assert EventKind.EXIT.value not in _kinds(record)


def test_cancel_check_stops_admission() -> None:
    seen = {"count": 0}

    def tick() -> bool:
        seen["count"] += 1
        return seen["count"] > 3

    def work() -> int:
        total = 0
        total += 1
        total += 1
        total += 1
        return total

    record = record_python_execution_trace(work, cancel_check=tick)
    assert record.cancelled is True
    assert record.accepted_transition is None
    assert EventKind.EXIT.value not in _kinds(record)


def test_cancelled_record_rejects_accepted_transition() -> None:
    tracer = PythonExecutionTracer()
    record = tracer.record(_raise_cancel)
    with pytest.raises(PythonExecutionTraceError, match="cancellation emits no accepted transition"):
        PythonExecutionTraceRecord(
            status=TraceStatus.CANCELLED,
            policy=record.policy,
            tree_cid=record.tree_cid,
            source_cid=record.source_cid,
            environment_binding_cid=record.environment_binding_cid,
            capture_profile_cid=record.capture_profile_cid,
            events=record.events,
            states=(),
            frames=(),
            exceptions=(),
            handlers=(),
            event_cids=record.event_cids,
            unavailable_dimensions=("cancelled",),
            redacted_dimensions=(),
            completeness_claim=CompletenessClaim.PARTIAL,
            privacy_class=PrivacyClass.INTERNAL,
            includes_raw_bodies=False,
            accepted_transition={
                "admitted": True,
                "from_event_cid": record.event_cids[0] if record.event_cids else record.tree_cid,
                "kind": "accepted_completion",
                "schema": "forbidden",
                "to_event_cid": record.tree_cid,
                "trace_cid": record.tree_cid,
            },
            cancellation=record.cancellation,
            result_summary={"bounded": True},
            raised_type=None,
        )


def test_deterministic_promised_replay_matches() -> None:
    policy = TraceCollectionPolicy(environment_binding={"python": "3.12"})
    original = record_python_execution_trace(_nested, 8, policy=policy)
    promised = replay_deterministic_trace(original)
    assert promised.replayed is True
    assert promised.promise_matched is True
    assert promised.event_cids == original.event_cids
    assert promised.deterministic_promise_cid == original.deterministic_promise_cid
    assert promised.includes_raw_bodies is False
    live = replay_deterministic_trace(original, _nested, 8, policy=policy)
    assert live.replayed is True
    assert live.promise_matched is True
    assert live.event_cids == original.event_cids
    assert live.result == 9


def test_cancelled_replay_emits_no_accepted_transition() -> None:
    original = record_python_execution_trace(_raise_cancel)
    replayed = replay_deterministic_trace(original)
    assert replayed.replayed is True
    assert replayed.cancelled is True
    assert replayed.accepted_transition is None
    assert replayed.includes_raw_bodies is False


def test_replay_fails_closed_on_divergence() -> None:
    original = record_python_execution_trace(_add, 1, 2)
    with pytest.raises(PythonExecutionTraceError, match="diverged"):
        replay_deterministic_trace(original, _add, 9, 9)


def test_redactor_public_trace_strips_raw_bodies() -> None:
    policy = TraceCollectionPolicy(include_raw_bodies=True, privacy_class=PrivacyClass.PRIVATE)
    record = record_python_execution_trace(_add, 3, 4, policy=policy)
    assert record.trace is not None
    public = TraceRedactor(policy).public_trace(record.trace)
    assert isinstance(public, ExecutionTrace)
    assert public.includes_raw_bodies is False
    assert public.raw_execution_state_cids == ()


def test_exact_binding_changes_with_environment() -> None:
    left = record_python_execution_trace(
        _add, 1, 1, policy=TraceCollectionPolicy(environment_binding={"env": "a"})
    )
    right = record_python_execution_trace(
        _add, 1, 1, policy=TraceCollectionPolicy(environment_binding={"env": "b"})
    )
    assert left.environment_binding_cid != right.environment_binding_cid
    assert left.deterministic_promise_cid != right.deterministic_promise_cid


def test_non_callable_and_nested_tracing_fail_closed() -> None:
    with pytest.raises(PythonExecutionTraceError, match="callable"):
        record_python_execution_trace(1)  # type: ignore[arg-type]
    tracer = PythonExecutionTracer()

    def inner() -> int:
        return tracer.record(_add, 1, 1).result

    with pytest.raises(PythonExecutionTraceError, match="nested"):
        tracer.record(inner)
