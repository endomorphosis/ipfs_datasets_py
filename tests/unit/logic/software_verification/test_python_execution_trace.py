"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    HERMETIC_TRACE_SCHEMA,
    PYTHON_EXECUTION_TRACE_INTERFACE,
    HermeticTraceRecord,
    PythonExecutionTraceError,
    PythonExecutionTracer,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceRedactor,
    TraceStatus,
    bind_environment_cid,
    bind_source_cid,
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


def _tree() -> str:
    return cid_for_bytes(b"tree:sawm-008-hermetic")


def _record(
    target: Callable[..., Any],
    *args: Any,
    policy: TraceCollectionPolicy | None = None,
    redactor: TraceRedactor | None = None,
    cancellation: TraceCancellation | None = None,
    **kwargs: Any,
) -> HermeticTraceRecord:
    return record_python_execution_trace(
        target,
        *args,
        tree_cid=_tree(),
        source_cid=bind_source_cid(target),
        environment_binding_cid=bind_environment_cid(),
        policy=policy,
        redactor=redactor,
        cancellation=cancellation,
        **kwargs,
    )


def _kinds(record: HermeticTraceRecord) -> list[str]:
    return [str(event.event_kind) for event in record.events]


def test_predicted_symbols_and_public_interfaces_are_present() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MODULE_PATH))
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "PythonExecutionTracer" in names
    assert "TraceCollectionPolicy" in names
    assert "TraceRedactor" in names
    assert "TraceCancellation" in names
    assert "record_python_execution_trace" in names
    assert "replay_deterministic_trace" in names
    assert PYTHON_EXECUTION_TRACE_INTERFACE == "PythonExecutionTrace@1"


def _add() -> int:
    left = 1
    right = 2
    return left + right


def test_call_return_and_line_events_bind_exact_tree_environment_and_location() -> None:
    record = _record(_add)
    kinds = _kinds(record)
    assert "call" in kinds
    assert "return" in kinds
    assert "line" in kinds
    assert record.status is TraceStatus.COMPLETED
    assert record.accepted_transitions
    assert all(item.accepted for item in record.accepted_transitions)
    assert record.tree_cid == _tree()
    env = bind_environment_cid()
    source = bind_source_cid(_add)
    for event in record.events:
        assert event.tree_cid == _tree()
        assert event.environment_binding_cid == env
        assert event.source_cid == source
        assert event.logical_name
        assert event.line is not None
        assert event.code_cid
        assert event.subject_cid
    tracer = PythonExecutionTracer()
    via_class = tracer.record(_add, tree_cid=_tree())
    assert via_class.tree_cid == record.tree_cid
    assert via_class.environment_binding_cid == env


def _handled() -> str:
    try:
        raise ValueError("boom")
    except ValueError:
        return "ok"


def test_exception_and_handler_events_are_collected() -> None:
    record = _record(_handled)
    kinds = set(_kinds(record))
    assert "raise" in kinds
    assert "handler" in kinds
    assert record.status is TraceStatus.COMPLETED
    raise_event = next(event for event in record.events if str(event.event_kind) == "raise")
    handler_event = next(
        event for event in record.events if str(event.event_kind) == "handler"
    )
    assert raise_event.exception_snapshot_cid
    assert handler_event.handler_state_cid
    assert raise_event.stack_frame_cids
    assert handler_event.stack_frame_cids


def _yield_driver() -> list[int]:
    def gen() -> Any:
        yield 1
        yield 2

    return list(gen())


def test_yield_events_are_collected_from_generator_fixtures() -> None:
    record = _record(_yield_driver)
    assert "yield" in _kinds(record)
    assert record.status is TraceStatus.COMPLETED


def _await_driver() -> int:
    import asyncio

    async def inner() -> int:
        await asyncio.sleep(0)
        return 7

    return asyncio.run(inner())


def test_await_events_are_collected_from_async_fixtures() -> None:
    record = _record(_await_driver)
    kinds = set(_kinds(record))
    assert "await" in kinds or "yield" in kinds
    assert record.status is TraceStatus.COMPLETED
    assert all(event.environment_binding_cid == bind_environment_cid() for event in record.events)


def _secret_holder() -> int:
    password = "test-only-password-value"
    api_key = "should-not-appear"
    return len(password) + len(api_key)


def test_secret_redaction_and_public_records_omit_raw_bodies() -> None:
    record = _record(_secret_holder, redactor=TraceRedactor())
    public = record.to_dict()
    encoded = json.dumps(public, sort_keys=True)
    assert public["includes_raw_bodies"] is False
    assert public["schema"] == HERMETIC_TRACE_SCHEMA
    assert "private_raw_bodies" not in public
    assert "private_trace" not in public
    assert "test-only-password-value" not in encoded
    assert "should-not-appear" not in encoded
    assert record.public_trace.includes_raw_bodies is False
    assert record.public_trace.raw_execution_state_cids == ()
    private_encoded = json.dumps(list(record.private_raw_bodies), sort_keys=True)
    assert "test-only-password-value" not in private_encoded
    assert "should-not-appear" not in private_encoded
    assert "password" not in private_encoded
    assert "api_key" not in private_encoded
    public_trace = json.dumps(record.public_trace.to_dict())
    assert "test-only-password-value" not in public_trace
    assert "should-not-appear" not in public_trace
    assert "password" not in json.dumps(record.result_summary)


def _fat_local() -> int:
    blob = "A" * 200_000
    return len(blob)


def test_payload_bounds_truncate_large_state_summaries() -> None:
    policy = TraceCollectionPolicy(max_text_chars=32, max_payload_bytes=256)
    record = _record(_fat_local, policy=policy)
    public = json.dumps(record.to_dict())
    assert "A" * 64 not in public
    for body in record.private_raw_bodies:
        encoded = json.dumps(body)
        assert "A" * 200 not in encoded
        assert len(encoded) < 8_192


def _network_probe() -> None:
    sock = socket.socket()
    try:
        sock.settimeout(0.0)
        sock.connect(("255.255.255.255", 1))
    finally:
        sock.close()


def test_test_only_network_denial_records_external_and_does_not_connect() -> None:
    policy = TraceCollectionPolicy(deny_network=True, deny_subprocess=True)
    record = _record(_network_probe, policy=policy)
    assert record.status in {TraceStatus.FAILED, TraceStatus.COMPLETED, TraceStatus.CANCELLED}
    public = json.dumps(record.to_dict())
    assert "255.255.255.255" not in public
    kinds = set(_kinds(record))
    assert "external" in kinds or record.error is not None or "raise" in kinds
    if record.status is TraceStatus.FAILED:
        assert record.error
        assert record.accepted_transitions == ()


def test_prestart_cancellation_emits_no_accepted_transition_and_does_not_run() -> None:
    seen: list[int] = []

    def target() -> int:
        seen.append(1)
        return 1

    cancellation = TraceCancellation()
    cancellation.cancel("prestart")
    record = _record(target, cancellation=cancellation)
    assert seen == []
    assert record.cancelled is True
    assert record.status is TraceStatus.CANCELLED
    assert record.accepted_transitions == ()
    assert record.to_dict()["accepted"] is False
    assert all(not item.accepted for item in record.accepted_transitions)


def test_mid_run_cancellation_emits_no_accepted_transition() -> None:
    cancellation = TraceCancellation()

    def target() -> int:
        value = 1
        cancellation.cancel("stop-now")
        return value + 1

    record = _record(target, cancellation=cancellation)
    assert record.status is TraceStatus.CANCELLED
    assert record.accepted_transitions == ()
    assert record.to_dict()["accepted"] is False
    assert record.public_trace.includes_raw_bodies is False


def test_deterministic_promised_replay_matches_public_identity() -> None:
    original = _record(_add)
    replay = replay_deterministic_trace(
        original,
        _add,
    )
    assert replay.promised is True
    assert replay.matched is True
    assert replay.replayed.public_trace.execution_trace_cid == original.public_trace.execution_trace_cid
    assert _kinds(replay.replayed) == _kinds(original)
    assert replay.replayed.tree_cid == original.tree_cid
    assert replay.replayed.environment_binding_cid == original.environment_binding_cid
    assert replay.replayed.source_cid == original.source_cid


def test_cancelled_replay_does_not_match_or_accept() -> None:
    cancellation = TraceCancellation()
    cancellation.cancel("nope")
    original = _record(_add)
    replay = replay_deterministic_trace(original, _add, cancellation=cancellation)
    assert replay.matched is False
    assert replay.replayed.accepted_transitions == ()


def test_collection_policy_rejects_invalid_bounds() -> None:
    with pytest.raises(PythonExecutionTraceError):
        TraceCollectionPolicy(max_events=0)
    with pytest.raises(PythonExecutionTraceError):
        TraceCollectionPolicy(collect_call="yes")  # type: ignore[arg-type]


def test_tracer_facade_replay_round_trip() -> None:
    tracer = PythonExecutionTracer(policy=TraceCollectionPolicy(line_stride=1))
    first = tracer.record(_add, tree_cid=_tree())
    second = tracer.replay(first, _add)
    assert second.matched is True
    assert first.to_dict()["includes_raw_bodies"] is False


def test_cold_import_has_no_network_socket_installer_subprocess_database_or_model_loads() -> None:
    script = r"""
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
            effects.append("write:" + str(args[0]))
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
    }:
        effects.append(event)
        raise AssertionError(f"forbidden import side effect: {event}")

sys.addaudithook(audit)

for name in list(sys.modules):
    if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
        del sys.modules[name]

import ipfs_datasets_py.logic.software_verification.python_execution_trace as mod

required = {
    "PythonExecutionTracer",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "TraceCancellation",
    "record_python_execution_trace",
    "replay_deterministic_trace",
}
missing = sorted(required - set(mod.__all__))
assert not missing, missing
assert mod.PYTHON_EXECUTION_TRACE_INTERFACE == "PythonExecutionTrace@1"

banned = {
    "torch",
    "transformers",
    "requests",
    "urllib3",
    "httpx",
    "duckdb",
    "watchdog",
    "pip",
}
loaded = set(sys.modules)
assert not (loaded & banned), sorted(loaded & banned)
assert os.environ == before, "import changed environment variables"
assert not effects, effects
print(json.dumps({"ok": True}, sort_keys=True))
"""
    environment = dict(os.environ)
    pythonpath = os.pathsep.join(
        [
            str(WORKSPACE_ROOT / "ipfs_datasets_py"),
            str(WORKSPACE_ROOT / "ipfs_kit_py"),
            str(WORKSPACE_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    environment.update(
        {
            "IPFS_DATASETS_AUTO_INSTALL": "0",
            "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
            "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
            "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": pythonpath,
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=WORKSPACE_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True}
