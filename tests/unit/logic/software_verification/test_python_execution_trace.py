"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    EventKind,
    PrivacyClass,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    HERMETIC_TRACE_RECORD_INTERFACE,
    HERMETIC_TRACE_REPLAY_INTERFACE,
    IMPORT_DATABASE_PERFORMED,
    IMPORT_INSTALLER_PERFORMED,
    IMPORT_MODEL_LOAD_PERFORMED,
    IMPORT_NETWORK_PERFORMED,
    IMPORT_REPO_SCAN_PERFORMED,
    IMPORT_SIDE_EFFECTS_PERFORMED,
    IMPORT_SOCKET_PERFORMED,
    IMPORT_SUBPROCESS_PERFORMED,
    IMPORT_WATCHER_PERFORMED,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    TRACE_CANCELLATION_INTERFACE,
    TRACE_COLLECTION_POLICY_INTERFACE,
    TRACE_REDACTOR_INTERFACE,
    HermeticTraceRecord,
    PythonExecutionTraceError,
    PythonExecutionTracer,
    ReplayPromise,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceDisposition,
    TraceRedactor,
    record_python_execution_trace,
    replay_deterministic_trace,
)

_PACKAGE = "ipfs_datasets_py.logic.software_verification.python_execution_trace"
_SECRET = "super-secret-value-xyz"
_REPO_ROOT = Path(__file__).resolve().parents[5]
_OPT_OUTS = {
    "IPFS_DATASETS_AUTO_INSTALL": "0",
    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
    "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
    "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _kinds(record: HermeticTraceRecord) -> list[str]:
    return [str(event.event_kind) for event in record.events]


def _add(left: int, right: int) -> int:
    return left + right


def _boom() -> int:
    try:
        raise ValueError("bounded")
    except ValueError:
        return 7


def _gen() -> Any:
    yield 1
    yield 2


async def _add_async(left: int, right: int) -> int:
    return left + right


async def _awaiting() -> int:
    return await _add_async(2, 3)


def _secret_holder() -> str:
    password = _SECRET
    api_key = _SECRET
    return password + api_key


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
    assert TRACE_COLLECTION_POLICY_INTERFACE == "TraceCollectionPolicy@1"
    assert TRACE_REDACTOR_INTERFACE == "TraceRedactor@1"
    assert TRACE_CANCELLATION_INTERFACE == "TraceCancellation@1"
    assert HERMETIC_TRACE_RECORD_INTERFACE == "HermeticTraceRecord@1"
    assert HERMETIC_TRACE_REPLAY_INTERFACE == "HermeticTraceReplay@1"
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)
    assert PythonExecutionTracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE
    assert TraceCollectionPolicy.INTERFACE == TRACE_COLLECTION_POLICY_INTERFACE
    assert TraceRedactor.INTERFACE == TRACE_REDACTOR_INTERFACE
    assert TraceCancellation.INTERFACE == TRACE_CANCELLATION_INTERFACE


def test_import_flags_record_no_side_effects() -> None:
    assert IMPORT_NETWORK_PERFORMED is False
    assert IMPORT_SOCKET_PERFORMED is False
    assert IMPORT_INSTALLER_PERFORMED is False
    assert IMPORT_SUBPROCESS_PERFORMED is False
    assert IMPORT_DATABASE_PERFORMED is False
    assert IMPORT_REPO_SCAN_PERFORMED is False
    assert IMPORT_WATCHER_PERFORMED is False
    assert IMPORT_MODEL_LOAD_PERFORMED is False
    assert IMPORT_SIDE_EFFECTS_PERFORMED is False


def test_cold_import_is_hermetic() -> None:
    script = f"""\
import json
import os
import sys
import threading

before = dict(os.environ)
before_modules = set(sys.modules)
effects = []

def forbidden(name):
    def call(*args, **kwargs):
        effects.append(name)
        raise AssertionError(f"forbidden import side effect: {{name}}")
    return call

os.system = forbidden("os.system")

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
            if "pycache" in path or path.endswith(".pyc"):
                return
            effects.append("write:" + path)
            raise AssertionError("forbidden import write")
    if event in {{
        "os.mkdir",
        "os.remove",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "socket.connect",
        "socket.getaddrinfo",
        "subprocess.Popen",
    }}:
        effects.append(event)
        raise AssertionError(f"forbidden import side effect: {{event}}")

sys.addaudithook(audit)
import {_PACKAGE} as tracing
assert tracing.PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
assert tracing.IMPORT_SIDE_EFFECTS_PERFORMED is False
assert tracing.IMPORT_NETWORK_PERFORMED is False
assert tracing.IMPORT_SOCKET_PERFORMED is False
assert tracing.IMPORT_SUBPROCESS_PERFORMED is False
assert tracing.IMPORT_DATABASE_PERFORMED is False
assert tracing.IMPORT_REPO_SCAN_PERFORMED is False
assert tracing.IMPORT_WATCHER_PERFORMED is False
assert tracing.IMPORT_MODEL_LOAD_PERFORMED is False
assert os.environ == before
assert not effects, effects
banned = {{"torch", "transformers", "requests", "httpx", "duckdb", "watchdog", "aiohttp"}}
loaded = set(sys.modules) - before_modules
assert not (loaded & banned), sorted(loaded & banned)
print(json.dumps({{"ok": True}}, sort_keys=True))
"""
    environment = dict(os.environ)
    environment.update(_OPT_OUTS)
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(_REPO_ROOT / "ipfs_datasets_py"),
            str(_REPO_ROOT / "ipfs_kit_py"),
            str(_REPO_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True}


def _stable_policy(**overrides: Any) -> TraceCollectionPolicy:
    fields: dict[str, Any] = {
        "collect_line": False,
        "collect_await": False,
        "max_events": 64,
    }
    fields.update(overrides)
    return TraceCollectionPolicy(**fields)


def test_call_return_and_exact_bindings() -> None:
    policy = _stable_policy()
    record = record_python_execution_trace(
        _add,
        args=(1, 2),
        policy=policy,
        environment_binding={"python": "3.12"},
    )
    kinds = _kinds(record)
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    assert record.disposition == TraceDisposition.OBSERVED.value
    assert record.accepted_transition is True
    assert record.operational_acceptance is False
    assert record.accepted_transition_record() is None
    assert record.public_trace.language == "python"
    assert record.tree_cid == record.public_trace.tree_cid
    assert record.source_cid == record.public_trace.source_cid
    assert record.environment_binding_cid == record.public_trace.environment_binding_cid
    assert record.code_cid
    assert all(event.tree_cid == record.tree_cid for event in record.events)
    assert all(event.source_cid == record.source_cid for event in record.events)
    assert all(
        event.environment_binding_cid == record.environment_binding_cid for event in record.events
    )
    assert any(event.logical_name.endswith("_add") for event in record.events)
    assert any(event.line is not None and event.line > 0 for event in record.events)
    assert record.result_summary["invoked"] is True
    assert record.result_summary["result"] == 3
    second = record_python_execution_trace(
        _add,
        args=(1, 2),
        policy=policy,
        environment_binding={"python": "3.12"},
    )
    assert record.public_trace.execution_trace_cid == second.public_trace.execution_trace_cid
    assert record.source_cid == second.source_cid
    assert record.environment_binding_cid == second.environment_binding_cid


def test_exception_and_handler_events_are_collected() -> None:
    record = record_python_execution_trace(_boom)
    kinds = set(_kinds(record))
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    assert record.exception_type == "ValueError"
    raise_event = next(event for event in record.events if str(event.event_kind) == "raise")
    assert raise_event.exception_snapshot_cid is not None
    handler_event = next(
        event for event in record.events if str(event.event_kind) in {"catch", "handler"}
    )
    assert handler_event.handler_state_cid is not None
    assert handler_event.stack_frame_cids


def test_yield_and_await_events_are_collected() -> None:
    generated = record_python_execution_trace(_gen)
    assert EventKind.YIELD.value in _kinds(generated)
    awaited = record_python_execution_trace(_awaiting)
    kinds = set(_kinds(awaited))
    assert kinds & {EventKind.AWAIT.value, EventKind.CALL.value, EventKind.RETURN.value}
    assert awaited.accepted_transition is True
    assert awaited.result_summary["result"] == 5


def test_payload_bounds_are_enforced() -> None:
    policy = TraceCollectionPolicy(max_events=3, collect_line=True, max_line_events=1)

    def busy() -> int:
        total = 0
        for item in range(16):
            total += item
        return total

    record = record_python_execution_trace(busy, policy=policy)
    assert len(record.events) <= 3
    assert "events" in record.unavailable_dimensions or len(record.events) == 3
    assert record.public_trace.completeness_claim != "full_state"


def test_secret_redaction_and_private_bodies_stay_off_public_records() -> None:
    policy = TraceCollectionPolicy(capture_locals=True, capture_raw_bodies=True)
    record = record_python_execution_trace(_secret_holder, policy=policy)
    public = record.to_public_dict()
    encoded = json.dumps(public, sort_keys=True)
    assert _SECRET not in encoded
    assert public["includes_raw_bodies"] is False
    assert public["privacy_class"] == PrivacyClass.PUBLIC.value
    assert record.public_trace.includes_raw_bodies is False
    assert record.public_trace.raw_execution_state_cids == ()
    assert "raw_bodies" not in public
    assert "_private_bodies" not in public
    assert "private_raw_bodies" not in public
    bodies = record.private_raw_bodies()
    assert bodies
    private_blob = json.dumps([body.to_dict() for body in bodies])
    assert _SECRET in private_blob or "password" in private_blob.lower()
    for event in record.events:
        payload = json.dumps(event.to_dict())
        assert _SECRET not in payload
        assert "password" not in event.payload
        assert "api_key" not in event.payload


def test_cancellation_emits_no_accepted_transition() -> None:
    cancellation = TraceCancellation()
    cancellation.cancel("preempt")
    record = record_python_execution_trace(_add, args=(1, 2), cancellation=cancellation)
    assert record.disposition == TraceDisposition.CANCELLED.value
    assert record.accepted_transition is False
    assert record.operational_acceptance is False
    assert record.accepted_transition_record() is None
    assert record.replay_promise == ReplayPromise.UNAVAILABLE.value
    public = record.to_public_dict()
    assert public["accepted_transition"] is False
    assert "admission" not in public
    with pytest.raises(PythonExecutionTraceError, match="no accepted transition"):
        replay_deterministic_trace(record)

    live = TraceCancellation()

    def work() -> str:
        live.cancel("mid-run")
        acc = 0
        for item in range(100):
            acc += item
        return "done"

    interrupted = record_python_execution_trace(work, cancellation=live)
    assert interrupted.accepted_transition is False
    assert interrupted.disposition == TraceDisposition.CANCELLED.value
    assert interrupted.cancellation_reason
    assert interrupted.public_trace.includes_raw_bodies is False


def test_test_only_network_isolation_denies_sockets() -> None:
    def poke() -> None:
        sock = socket.socket()
        try:
            sock.connect(("127.0.0.1", 1))
        finally:
            sock.close()

    record = record_python_execution_trace(poke)
    assert record.accepted_transition is False
    assert record.disposition == TraceDisposition.DENIED.value
    assert "external" in record.unavailable_dimensions
    assert EventKind.EXTERNAL.value in _kinds(record)
    assert record.replay_promise == ReplayPromise.UNAVAILABLE.value


def test_deterministic_promised_replay_matches() -> None:
    policy = _stable_policy()
    record = record_python_execution_trace(
        _add,
        args=(4, 5),
        policy=policy,
        environment_binding={"python": "3.12"},
    )
    promised = replay_deterministic_trace(record)
    assert promised.matched is True
    assert promised.promised is True
    assert promised.accepted_transition is True
    assert promised.operational_acceptance is False
    assert promised.event_kinds == tuple(_kinds(record))
    replayed = replay_deterministic_trace(
        record,
        target=_add,
        args=(4, 5),
        policy=policy,
    )
    assert replayed.matched is True
    assert replayed.promised is False
    assert replayed.event_kinds == tuple(_kinds(record))
    with pytest.raises(PythonExecutionTraceError, match="diverged"):
        replay_deterministic_trace(record, target=_boom)


def test_public_record_never_includes_raw_bodies_or_acceptance() -> None:
    policy = TraceCollectionPolicy(capture_raw_bodies=True, capture_locals=True)
    record = record_python_execution_trace(_add, args=(8, 9), policy=policy)
    public = record.to_dict()
    assert public["includes_raw_bodies"] is False
    assert public["operational_acceptance"] is False
    assert public["public_trace"]["includes_raw_bodies"] is False
    assert public["public_trace"]["raw_execution_state_cids"] == []
    assert public["public_trace"]["privacy_class"] == PrivacyClass.PUBLIC.value
    assert record.private_raw_bodies()
    cloned = json.loads(json.dumps(public))
    assert cloned["includes_raw_bodies"] is False
    assert "locals_preview" not in json.dumps(cloned)


def test_redactor_drops_secret_and_forbidden_fields() -> None:
    redactor = TraceRedactor()
    payload, dimensions = redactor.public_payload(
        {
            "password": "nope",
            "api_key": "nope",
            "locals": {"x": 1, "secret": "nope"},
            "safe": 2,
        },
        budget=2048,
    )
    assert "password" not in payload
    assert "api_key" not in payload
    assert "secret" not in payload.get("locals", {})
    assert payload["safe"] == 2
    assert payload["locals"]["x"] == 1
    assert "password" in dimensions or "secret" in dimensions or "api_key" in dimensions
