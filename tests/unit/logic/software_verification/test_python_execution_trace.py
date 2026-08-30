"""Hermetic Python execution tracing coverage (SAWM-008)."""

from __future__ import annotations

import ast
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    PrivacyClass,
)
from ipfs_datasets_py.logic.software_verification import python_execution_trace as _trace_module
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    DEFAULT_ADMITTED_EVENT_KINDS,
    HERMETIC_TRACE_EVIDENCE,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    TRACE_CANCELLATION_INTERFACE,
    TRACE_COLLECTION_POLICY_INTERFACE,
    TRACE_REDACTOR_INTERFACE,
    PythonExecutionTraceError,
    PythonExecutionTraceRecord,
    PythonExecutionTracer,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceDisposition,
    TraceRedactor,
    record_python_execution_trace,
    replay_deterministic_trace,
)


WORKSPACE = Path(__file__).resolve().parents[5]
IMPLEMENTATION = Path(_trace_module.__file__).resolve()
_OPT_OUTS = {
    "IPFS_DATASETS_AUTO_INSTALL": "0",
    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
    "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
    "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}
_FORBIDDEN_IMPORTS = frozenset(
    {
        "aiohttp",
        "anthropic",
        "docker",
        "duckdb",
        "ensurepip",
        "ftplib",
        "git",
        "http",
        "http.client",
        "huggingface_hub",
        "multiprocessing",
        "openai",
        "paramiko",
        "pip",
        "psycopg2",
        "pymongo",
        "requests",
        "setuptools",
        "smtplib",
        "socket",
        "sqlite3",
        "ssl",
        "subprocess",
        "telnetlib",
        "torch",
        "transformers",
        "urllib",
        "urllib.request",
        "urllib3",
        "watchdog",
    }
)


def _policy(**overrides: Any) -> TraceCollectionPolicy:
    fields: dict[str, Any] = {
        "tree_cid": cid_for_bytes(b"tree:hermetic-trace-v1"),
        "environment_binding_cid": cid_for_bytes(b"env:python-3.12-hermetic"),
    }
    fields.update(overrides)
    return TraceCollectionPolicy(**fields)


def _kinds(record: PythonExecutionTraceRecord) -> list[str]:
    return [str(event.event_kind) for event in record.events]


def _record(target: Callable[..., Any], *, policy: TraceCollectionPolicy | None = None, **kwargs: Any) -> PythonExecutionTraceRecord:
    return record_python_execution_trace(target, policy=policy or _policy(), **kwargs)


def _run_coroutine(coro: Any) -> Any:
    stack = [coro]
    send_value = None
    while stack:
        current = stack[-1]
        try:
            yielded = current.send(send_value)
        except StopIteration as exc:
            stack.pop()
            send_value = exc.value
        else:
            if inspect.iscoroutine(yielded):
                stack.append(yielded)
                send_value = None
            else:
                raise AssertionError("nondeterministic await is unavailable in hermetic fixtures")
    return send_value


def ping() -> int:
    return pong(1)


def pong(value: int) -> int:
    return value + 1


def boom() -> int:
    try:
        raise ValueError("bounded")
    except ValueError:
        return 7


def produce() -> list[int]:
    def gen() -> Any:
        yield 1
        yield 2

    return list(gen())


def await_inner() -> int:
    async def inner() -> int:
        return 4

    async def outer() -> int:
        return await inner()

    return _run_coroutine(outer())


def secret_holder() -> dict[str, str]:
    password = "s3cret-value"
    session_token = "tok-live"
    return {"ok": "yes", "password": password, "session_token": session_token}


def fat_payload() -> dict[str, str]:
    return {f"key-{index:03d}": "v" * 80 for index in range(80)}


def liney() -> int:
    total = 0
    total += 1
    total += 2
    total += 3
    return total


def attempt_connect() -> None:
    import socket

    sock = socket.socket()
    try:
        sock.connect(("127.0.0.1", 1))
    finally:
        sock.close()


def cancellable(token: TraceCancellation) -> int:
    total = 0
    for index in range(8):
        token.raise_if_cancelled()
        total += index
    return total


def test_public_interfaces_are_versioned_and_exported() -> None:
    assert PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
    assert TRACE_COLLECTION_POLICY_INTERFACE == "TraceCollectionPolicy@1"
    assert TRACE_REDACTOR_INTERFACE == "TraceRedactor@1"
    assert TRACE_CANCELLATION_INTERFACE == "TraceCancellation@1"
    assert HERMETIC_TRACE_EVIDENCE == "sawm/hermetic-trace@1"
    assert EventKind.CALL.value in DEFAULT_ADMITTED_EVENT_KINDS
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)
    tracer = PythonExecutionTracer(_policy())
    assert tracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE


def test_implementation_ast_forbids_side_effect_imports() -> None:
    tree = ast.parse(IMPLEMENTATION.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            imported.add(node.module)
    forbidden = sorted(imported & _FORBIDDEN_IMPORTS)
    assert not forbidden, forbidden
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                calls.add(f"{func.value.id}.{func.attr}")
            elif isinstance(func, ast.Name):
                calls.add(func.id)
    assert "subprocess.Popen" not in calls
    assert "os.system" not in calls
    assert "socket.connect" not in calls


def test_cold_import_has_no_network_socket_installer_subprocess_or_model_loads() -> None:
    script = r'''
import json
import os
import sys
import threading

before = dict(os.environ)
effects = []

def forbidden(name):
    def call(*args, **kwargs):
        effects.append(name)
        raise AssertionError(f"forbidden import side effect: {name}")
    return call

os.system = forbidden("os.system")
for name in ("posix_spawn", "posix_spawnp", "spawnv", "spawnve", "spawnvp", "spawnvpe"):
    if hasattr(os, name):
        setattr(os, name, forbidden("os." + name))

def _thread_start(self, *args, **kwargs):
    effects.append("threading.Thread.start")
    raise AssertionError("forbidden import side effect: threading.Thread.start")

threading.Thread.start = _thread_start

def audit(event, args):
    if event == "open" and len(args) > 2:
        flags = args[2]
        if isinstance(flags, int) and flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        ):
            path = str(args[0])
            if "pycache" not in path and not path.endswith(".pyc"):
                effects.append("write:" + path)
                raise AssertionError("forbidden import write")
    if event in {
        "os.mkdir",
        "os.remove",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "socket.connect",
        "socket.getaddrinfo",
        "subprocess.Popen",
        "sqlite3.connect",
    }:
        effects.append(event)
        raise AssertionError(f"forbidden import side effect: {event}")

sys.addaudithook(audit)
import ipfs_datasets_py.logic.software_verification.python_execution_trace as mod
assert os.environ == before, "import changed environment variables"
assert not effects, effects
assert callable(mod.record_python_execution_trace)
assert callable(mod.replay_deterministic_trace)
print(json.dumps({"ok": True}, sort_keys=True))
'''
    environment = dict(os.environ)
    environment.update(_OPT_OUTS)
    environment["PYTHONPATH"] = os.pathsep.join(sys.path)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(WORKSPACE),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True}


def test_call_and_return_fixture_binds_exact_code_and_environment() -> None:
    policy = _policy()
    record = _record(ping, policy=policy)
    kinds = _kinds(record)
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    assert record.accepted_transition is None
    assert record.disposition == TraceDisposition.COMPLETE
    for event in record.events:
        assert event.tree_cid == policy.tree_cid
        assert event.environment_binding_cid == policy.environment_binding_cid
        assert event.source_cid == record.private_trace.source_cid
        assert event.language == "python"
        payload = event.identity_payload()
        assert "timestamp" not in payload
        assert "wall_clock" not in payload
        assert "pid" not in payload
        assert "hostname" not in payload
    other_env = _record(ping, policy=_policy(environment_binding_cid=cid_for_bytes(b"env:other")))
    assert other_env.private_trace.execution_trace_cid != record.private_trace.execution_trace_cid
    other_tree = _record(ping, policy=_policy(tree_cid=cid_for_bytes(b"tree:other")))
    assert other_tree.private_trace.execution_trace_cid != record.private_trace.execution_trace_cid
    names = {event.logical_name for event in record.events}
    assert any(name.endswith("ping") or name.endswith("pong") for name in names)


def test_exception_and_handler_fixture() -> None:
    record = _record(boom, policy=_policy(collect_line_events=True))
    kinds = set(_kinds(record))
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    assert record.exceptions
    assert record.exceptions[0].exception_type == "ValueError"
    assert record.exceptions[0].future_execution is False
    assert record.handlers
    assert record.result_summary.get("value") == 7
    assert record.accepted_transition is None


def test_yield_fixture() -> None:
    record = _record(produce, policy=_policy(collect_line_events=False))
    assert EventKind.YIELD.value in _kinds(record)
    assert record.result_summary.get("value") == [1, 2]


def test_async_await_fixture() -> None:
    record = _record(await_inner, policy=_policy(collect_line_events=False))
    kinds = _kinds(record)
    assert EventKind.AWAIT.value in kinds or EventKind.YIELD.value in kinds
    assert record.result_summary.get("value") == 4
    for event in record.events:
        assert event.tree_cid == record.private_trace.tree_cid
        assert event.environment_binding_cid == record.private_trace.environment_binding_cid


def test_payload_bounds_are_enforced() -> None:
    policy = _policy(max_summary_bytes=512, max_text_chars=32, collect_line_events=False)
    record = _record(fat_payload, policy=policy)
    for event in record.events:
        encoded = json.dumps(event.to_dict(), sort_keys=True)
        assert len(encoded.encode("utf-8")) <= 16_384
    assert record.private_trace.completeness_claim != CompletenessClaim.FULL_STATE.value
    assert "heap" in record.private_trace.unavailable_dimensions


def test_secret_redaction_omits_private_values() -> None:
    record = _record(secret_holder, policy=_policy(collect_line_events=False, collect_locals=True))
    public = record.to_public_dict()
    public_blob = json.dumps(public, sort_keys=True)
    assert "s3cret-value" not in public_blob
    assert "tok-live" not in public_blob
    private_blob = json.dumps([event.to_dict() for event in record.events], sort_keys=True)
    assert "s3cret-value" not in private_blob
    assert "tok-live" not in private_blob
    for event in record.events:
        locals_payload = event.payload.get("locals", {})
        assert "password" not in locals_payload
        assert "session_token" not in locals_payload
        value = event.payload.get("value")
        if isinstance(value, dict):
            assert "password" not in value
            assert "session_token" not in value


def test_network_is_denied_during_collection() -> None:
    record = _record(attempt_connect, policy=_policy(collect_line_events=False, isolate_network=True))
    public = record.to_public_dict()
    assert public["accepted_transition"] is None
    assert record.accepted_transition is None
    kinds = _kinds(record)
    denied = [
        event
        for event in record.events
        if str(event.event_kind) == EventKind.EXTERNAL.value and event.payload.get("denied") is True
    ]
    assert denied or record.target_exception_type == "PythonExecutionTraceError"
    assert EventKind.EXTERNAL.value in kinds or record.target_exception_type == "PythonExecutionTraceError"
    assert record.private_trace.privacy_class != PrivacyClass.PUBLIC.value or not record.private_trace.includes_raw_bodies


def test_cancellation_emits_no_accepted_transition() -> None:
    token = TraceCancellation(after_events=3, reason="test-stop")
    record = _record(
        ping,
        policy=_policy(collect_line_events=True),
        cancellation=token,
    )
    assert token.accepted_transition is None
    assert record.accepted_transition is None
    assert record.disposition == TraceDisposition.CANCELLED
    assert record.cancellation is not None
    assert record.cancellation.accepted_transition is None
    assert record.cancellation.cancelled is True
    public = record.to_public_dict()
    assert public["accepted_transition"] is None
    assert public["disposition"] == TraceDisposition.CANCELLED.value
    assert public["cancellation"]["accepted_transition"] is None
    replayed = replay_deterministic_trace(record)
    assert replayed.accepted_transition is None
    assert replayed.disposition == TraceDisposition.CANCELLED
    live = TraceCancellation()
    live.cancel("operator-abort")
    with pytest.raises(Exception):
        live.raise_if_cancelled()
    assert live.accepted_transition is None


def test_private_raw_trace_bodies_never_enter_public_records() -> None:
    record = _record(ping, policy=_policy(include_raw_bodies=True, collect_locals=True))
    assert record.private_trace.includes_raw_bodies is True
    assert record.private_trace.privacy_class == PrivacyClass.PRIVATE.value
    assert record.public_record.includes_raw_bodies is False
    assert record.public_record.privacy_class == PrivacyClass.PUBLIC.value
    assert record.public_record.raw_execution_state_cids == ()
    public = record.to_public_dict()
    assert public["includes_raw_bodies"] is False
    assert public["trace"]["includes_raw_bodies"] is False
    assert public["trace"]["raw_execution_state_cids"] == []
    public_blob = json.dumps(public, sort_keys=True)
    assert '"includes_raw_bodies": true' not in public_blob
    for event in public["events"]:
        assert event["includes_raw_bodies"] is False
        assert "locals" not in event["payload"]
    with pytest.raises(PythonExecutionTraceError, match="remain private"):
        TraceCollectionPolicy(
            tree_cid=cid_for_bytes(b"tree:public-raw"),
            environment_binding_cid=cid_for_bytes(b"env:public-raw"),
            include_raw_bodies=True,
            privacy_class=PrivacyClass.PUBLIC,
        )
    redactor = TraceRedactor()
    assert redactor.public_trace(record.private_trace).includes_raw_bodies is False


def test_deterministic_promised_replay() -> None:
    policy = _policy(collect_line_events=False)
    first = _record(ping, policy=policy)
    second = _record(ping, policy=policy)
    assert first.private_trace.execution_trace_cid == second.private_trace.execution_trace_cid
    replayed = replay_deterministic_trace(first)
    again = replay_deterministic_trace(first)
    assert replayed.replayed is True
    assert again.private_trace.execution_trace_cid == first.private_trace.execution_trace_cid
    assert replayed.private_trace.execution_trace_cid == again.private_trace.execution_trace_cid
    assert replayed.public_record.includes_raw_bodies is False
    assert replayed.accepted_transition is None
    assert [event.program_event_cid for event in replayed.events] == [
        event.program_event_cid for event in first.events
    ]


def test_line_events_are_policy_bounded() -> None:
    bounded = _record(liney, policy=_policy(collect_line_events=True, max_line_events=1, max_events=64))
    line_count = _kinds(bounded).count(EventKind.LINE.value)
    assert line_count <= 1
    disabled = _record(liney, policy=_policy(collect_line_events=False))
    assert EventKind.LINE.value not in _kinds(disabled)
    exploded = _record(
        liney,
        policy=_policy(collect_line_events=True, max_events=3, max_line_events=50),
    )
    assert exploded.disposition in {TraceDisposition.BOUNDED, TraceDisposition.COMPLETE}
    assert exploded.accepted_transition is None
    if exploded.disposition == TraceDisposition.BOUNDED:
        assert "remaining_events" in exploded.private_trace.unavailable_dimensions


def test_tracer_record_method_matches_function() -> None:
    policy = _policy(collect_line_events=False)
    tracer = PythonExecutionTracer(policy)
    via_class = tracer.record(ping)
    via_function = record_python_execution_trace(ping, policy=policy)
    assert via_class.private_trace.execution_trace_cid == via_function.private_trace.execution_trace_cid


def test_shell_and_builtin_targets_are_unavailable() -> None:
    with pytest.raises(PythonExecutionTraceError, match="builtin"):
        record_python_execution_trace(len, args=("x",), policy=_policy())
    with pytest.raises(PythonExecutionTraceError, match="callable"):
        record_python_execution_trace(None, policy=_policy())  # type: ignore[arg-type]


def test_public_record_excludes_accepted_transition_even_on_success() -> None:
    record = _record(ping, policy=_policy(collect_line_events=False))
    assert record.accepted_transition is None
    public = record.to_public_dict()
    assert "accepted_transition" in public
    assert public["accepted_transition"] is None
    assert record.disposition == TraceDisposition.COMPLETE
