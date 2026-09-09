"""Hermetic Python execution tracing (SAWM-008)."""

from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    PrivacyClass,
    SECRET_FIELD_MARKERS,
)
from ipfs_datasets_py.logic.software_verification.python_execution_trace import (
    IMPORT_DATABASE_PERFORMED,
    IMPORT_INSTALLER_PERFORMED,
    IMPORT_MODEL_LOAD_PERFORMED,
    IMPORT_NETWORK_PERFORMED,
    IMPORT_SCAN_PERFORMED,
    IMPORT_SOCKET_PERFORMED,
    IMPORT_SUBPROCESS_PERFORMED,
    IMPORT_WATCHER_PERFORMED,
    PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE,
    PYTHON_EXECUTION_TRACER_INTERFACE,
    PYTHON_EXECUTION_TRACE_RECORD_INTERFACE,
    TRACE_CANCELLATION_INTERFACE,
    TRACE_COLLECTION_POLICY_INTERFACE,
    TRACE_REDACTOR_INTERFACE,
    CollectionOutcome,
    PythonExecutionReplayReceipt,
    PythonExecutionTraceError,
    PythonExecutionTraceRecord,
    PythonExecutionTracer,
    TraceCancellation,
    TraceCollectionPolicy,
    TraceRedactor,
    module_forbids_import_time_effects,
    record_python_execution_trace,
    replay_deterministic_trace,
)


MODULE_PATH = Path(
    sys.modules[
        "ipfs_datasets_py.logic.software_verification.python_execution_trace"
    ].__file__
).resolve()
WORKSPACE_ROOT = Path(__file__).resolve().parents[5]
_FORBIDDEN_IMPORTS = {
    "aiohttp",
    "celery",
    "duckdb",
    "httpx",
    "psycopg2",
    "pymongo",
    "redis",
    "requests",
    "socket",
    "sqlite3",
    "ssl",
    "subprocess",
    "torch",
    "transformers",
    "urllib3",
    "watchdog",
}
_OPT_OUTS = {
    "IPFS_DATASETS_AUTO_INSTALL": "0",
    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
    "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
    "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def ping() -> int:
    return 1


def callee(value: int) -> int:
    return value + 1


def caller() -> int:
    return callee(1)


def handled_error() -> str:
    try:
        raise ValueError("bounded")
    except ValueError:
        return "ok"


def unhandled_error() -> None:
    raise RuntimeError("boom")


def gen() -> object:
    yield 1
    yield 2


def run_gen() -> list[int]:
    return list(gen())


async def _inner_coro() -> int:
    return 1


async def _outer_coro() -> int:
    return await _inner_coro()


def run_async() -> int:
    coro = _outer_coro()
    yielded: object = None
    try:
        while True:
            yielded = coro.send(yielded)
    except StopIteration as stop:
        return int(stop.value)


def secret_holder() -> int:
    password = "s3cret"
    api_key = "k"
    x = 1
    return x + len(password) + len(api_key)


def huge_payload() -> str:
    blob = "a" * 10_000
    return blob[:3]


def network_probe() -> None:
    socket.create_connection(("203.0.113.1", 80), timeout=0.05)


def subprocess_probe() -> None:
    subprocess.run([sys.executable, "-c", "print(1)"], check=False)


def cancel_now(token: TraceCancellation) -> int:
    token.cancel("stop")
    token.throw_if_cancelled()
    return 1


def raise_cancel() -> int:
    raise TraceCancellation("stop")


def looping(limit: int) -> int:
    total = 0
    for item in range(limit):
        total += item
    return total


def _kinds(record: PythonExecutionTraceRecord) -> set[str]:
    return {str(event.event_kind) for event in record.events}


def _public_blob(record: PythonExecutionTraceRecord) -> str:
    payload = {
        "events": [event.to_dict() for event in record.events],
        "public_states": [state.to_dict() for state in record.public_states],
        "public_trace": record.public_trace.to_dict(),
        "receipt": record.receipt.to_dict(),
    }
    return json.dumps(payload, sort_keys=True)


def test_public_interfaces_and_symbols_are_versioned() -> None:
    assert PYTHON_EXECUTION_TRACER_INTERFACE == "PythonExecutionTracer@1"
    assert TRACE_COLLECTION_POLICY_INTERFACE == "TraceCollectionPolicy@1"
    assert TRACE_REDACTOR_INTERFACE == "TraceRedactor@1"
    assert TRACE_CANCELLATION_INTERFACE == "TraceCancellation@1"
    assert PYTHON_EXECUTION_TRACE_RECORD_INTERFACE == "PythonExecutionTraceRecord@1"
    assert PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE == "PythonExecutionReplayReceipt@1"
    assert callable(record_python_execution_trace)
    assert callable(replay_deterministic_trace)
    assert PythonExecutionTracer.INTERFACE == PYTHON_EXECUTION_TRACER_INTERFACE
    assert TraceCollectionPolicy.INTERFACE == TRACE_COLLECTION_POLICY_INTERFACE
    assert TraceRedactor.INTERFACE == TRACE_REDACTOR_INTERFACE
    assert TraceCancellation.INTERFACE == TRACE_CANCELLATION_INTERFACE
    assert TraceCancellation.accepted_transition is False


def test_import_time_side_effect_flags_remain_false() -> None:
    flags = module_forbids_import_time_effects()
    assert flags == {
        "database": False,
        "installer": False,
        "model_load": False,
        "network": False,
        "repo_scan": False,
        "socket": False,
        "subprocess": False,
        "watcher": False,
    }
    assert IMPORT_SCAN_PERFORMED is False
    assert IMPORT_NETWORK_PERFORMED is False
    assert IMPORT_SOCKET_PERFORMED is False
    assert IMPORT_INSTALLER_PERFORMED is False
    assert IMPORT_SUBPROCESS_PERFORMED is False
    assert IMPORT_DATABASE_PERFORMED is False
    assert IMPORT_WATCHER_PERFORMED is False
    assert IMPORT_MODEL_LOAD_PERFORMED is False


def test_module_ast_has_no_forbidden_top_level_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(_FORBIDDEN_IMPORTS)


def test_cold_import_starts_no_network_socket_installer_subprocess_or_model() -> None:
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
banned = ("torch", "transformers", "requests", "urllib3", "httpx", "watchdog", "duckdb")
loaded = [name for name in banned if name in sys.modules]
assert not loaded, loaded
assert mod.IMPORT_SCAN_PERFORMED is False
assert mod.IMPORT_NETWORK_PERFORMED is False
assert callable(mod.record_python_execution_trace)
assert callable(mod.replay_deterministic_trace)
assert os.environ == before
assert not effects, effects
print(json.dumps({"ok": True}, sort_keys=True))
"""
    environment = dict(os.environ)
    environment.update(_OPT_OUTS)
    pythonpath = os.pathsep.join(
        [
            str(WORKSPACE_ROOT / "ipfs_datasets_py"),
            str(WORKSPACE_ROOT / "ipfs_kit_py"),
            str(WORKSPACE_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    environment["PYTHONPATH"] = pythonpath
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(WORKSPACE_ROOT),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout.splitlines()[-1]) == {"ok": True}


def test_call_and_return_events_bind_exact_code_and_environment() -> None:
    env = {"language": "python", "python_major": "3", "python_minor": "12"}
    record = record_python_execution_trace(
        caller,
        environment_binding=env,
        policy=TraceCollectionPolicy(collect_line=False),
    )
    assert record.outcome == CollectionOutcome.COMPLETED.value
    assert record.binding.environment_binding == env
    assert record.binding.language == "python"
    kinds = _kinds(record)
    assert EventKind.CALL.value in kinds
    assert EventKind.RETURN.value in kinds
    for event in record.events:
        assert event.tree_cid == record.binding.tree_cid
        assert event.source_cid == record.binding.source_cid
        assert event.environment_binding_cid == record.binding.environment_binding_cid
        assert event.subject_cid == record.binding.subject_cid
        assert "timestamp" not in event.identity_payload()
        assert "wall_clock" not in event.identity_payload()
        assert "hostname" not in event.identity_payload()
    names = {event.logical_name for event in record.events}
    assert any("caller" in name for name in names)
    assert any("callee" in name for name in names)


def test_exact_binding_changes_identity() -> None:
    left = record_python_execution_trace(
        ping, environment_binding={"language": "python", "slot": "a"}
    )
    right = record_python_execution_trace(
        ping, environment_binding={"language": "python", "slot": "b"}
    )
    assert left.binding.environment_binding_cid != right.binding.environment_binding_cid
    assert left.private_trace.execution_trace_cid != right.private_trace.execution_trace_cid
    same = record_python_execution_trace(
        ping, environment_binding={"language": "python", "slot": "a"}
    )
    assert same.binding.environment_binding_cid == left.binding.environment_binding_cid
    assert same.public_trace.execution_trace_cid == left.public_trace.execution_trace_cid
    assert same.private_trace.execution_trace_cid == left.private_trace.execution_trace_cid


def test_exception_and_handler_events_are_collected() -> None:
    record = record_python_execution_trace(handled_error)
    kinds = _kinds(record)
    assert EventKind.RAISE.value in kinds
    assert EventKind.CATCH.value in kinds or EventKind.HANDLER.value in kinds
    raised = next(event for event in record.events if event.event_kind == EventKind.RAISE.value)
    assert raised.exception_snapshot_cid is not None
    caught = [
        event
        for event in record.events
        if event.event_kind in {EventKind.CATCH.value, EventKind.HANDLER.value}
    ]
    assert caught
    assert any(event.handler_state_cid is not None for event in caught)


def test_uncaught_exception_is_failed_observation_not_acceptance() -> None:
    record = record_python_execution_trace(unhandled_error)
    assert record.outcome == CollectionOutcome.FAILED.value
    assert record.accepted_transition is False
    assert record.operational_acceptance is False
    assert EventKind.RAISE.value in _kinds(record)


def test_yield_events_are_collected() -> None:
    record = record_python_execution_trace(run_gen)
    assert record.outcome == CollectionOutcome.COMPLETED.value
    assert EventKind.YIELD.value in _kinds(record)


def test_await_events_are_collected() -> None:
    record = record_python_execution_trace(run_async)
    assert record.outcome == CollectionOutcome.COMPLETED.value
    kinds = _kinds(record)
    assert EventKind.AWAIT.value in kinds or EventKind.CALL.value in kinds
    assert any("inner_coro" in event.logical_name or "outer_coro" in event.logical_name for event in record.events)


def test_line_events_are_policy_bounded() -> None:
    policy = TraceCollectionPolicy(max_line_events=2, max_events=64)
    record = record_python_execution_trace(looping, 8, policy=policy)
    line_events = [event for event in record.events if event.event_kind == EventKind.LINE.value]
    assert len(line_events) <= 2
    bounded = record_python_execution_trace(
        looping, 50, policy=TraceCollectionPolicy(max_events=6, collect_line=True)
    )
    assert bounded.bounded is True
    assert bounded.outcome == CollectionOutcome.BOUNDED.value
    assert len(bounded.events) <= 6
    assert bounded.operational_acceptance is False


def test_payload_bounds_truncate_large_summaries() -> None:
    redactor = TraceRedactor()
    summary, _redacted = redactor.summarize_mapping(
        {"blob": "a" * 10_000, "count": 3},
        max_items=8,
        max_chars=16,
    )
    assert summary["blob"] == "a" * 16
    assert summary["count"] == 3
    record = record_python_execution_trace(
        huge_payload,
        policy=TraceCollectionPolicy(include_raw_bodies=True, max_summary_chars=16),
    )
    dumped = json.dumps([state.to_dict() for state in record.states])
    assert "a" * 10_000 not in dumped
    public = _public_blob(record)
    assert "a" * 10_000 not in public


def test_secret_redaction_never_enters_records() -> None:
    redactor = TraceRedactor()
    mapping, redacted = redactor.summarize_mapping(
        {"password": "s3cret", "api_key": "k", "x": 1},
        max_items=8,
        max_chars=32,
    )
    assert "password" not in mapping
    assert "api_key" not in mapping
    assert mapping["x"] == 1
    assert "secrets" in redacted
    record = record_python_execution_trace(
        secret_holder,
        policy=TraceCollectionPolicy(include_raw_bodies=True),
    )
    blob = json.dumps(
        {
            "events": [event.to_dict() for event in record.events],
            "private": record.private_trace.to_dict(),
            "public": record.public_trace.to_dict(),
            "states": [state.to_dict() for state in record.states],
        }
    )
    for marker in SECRET_FIELD_MARKERS:
        assert f'"{marker}"' not in blob
    assert "s3cret" not in blob
    assert record.private_trace.completeness_claim != CompletenessClaim.FULL_STATE.value or (
        "password" not in blob
    )


def test_private_raw_bodies_never_enter_public_records() -> None:
    record = record_python_execution_trace(
        caller,
        policy=TraceCollectionPolicy(include_raw_bodies=True),
    )
    assert record.policy.include_raw_bodies is True
    assert record.policy.privacy_class == PrivacyClass.PRIVATE.value
    assert record.public_trace.includes_raw_bodies is False
    assert record.public_trace.raw_execution_state_cids == ()
    assert record.public_trace.privacy_class == PrivacyClass.PUBLIC.value
    assert "raw_body" in record.public_trace.redacted_dimensions
    assert record.public_trace.execution_trace_cid != record.private_trace.execution_trace_cid
    for state in record.public_states:
        assert state.includes_raw_bodies is False
        assert state.privacy_class == PrivacyClass.PUBLIC.value
    public = record.public_trace.to_dict()
    assert public["includes_raw_bodies"] is False
    assert public["raw_execution_state_cids"] == []
    blob = json.dumps(public, sort_keys=True)
    assert '"includes_raw_bodies": false' in blob or '"includes_raw_bodies":false' in blob


def test_redactor_rejects_public_raw_trace() -> None:
    record = record_python_execution_trace(
        ping, policy=TraceCollectionPolicy(include_raw_bodies=True)
    )
    public = TraceRedactor().public_trace(record.private_trace)
    assert public.includes_raw_bodies is False
    assert public.raw_execution_state_cids == ()
    assert public.privacy_class == PrivacyClass.PUBLIC.value


def test_cancellation_emits_no_accepted_transition() -> None:
    token = TraceCancellation("token")
    record = record_python_execution_trace(cancel_now, token, cancellation=token)
    assert record.outcome == CollectionOutcome.CANCELLED.value
    assert record.accepted_transition is False
    assert record.operational_acceptance is False
    assert record.receipt.accepted_transition is False
    assert record.receipt.cancelled is True
    assert record.cancellation_reason == "stop"
    raised = record_python_execution_trace(raise_cancel)
    assert raised.outcome == CollectionOutcome.CANCELLED.value
    assert raised.accepted_transition is False
    assert raised.operational_acceptance is False
    pre = TraceCancellation("already")
    pre.cancel("already")
    skipped = record_python_execution_trace(ping, cancellation=pre)
    assert skipped.outcome == CollectionOutcome.CANCELLED.value
    assert skipped.accepted_transition is False
    assert skipped.receipt.accepted_transition is False


def test_network_and_subprocess_are_denied_during_collection() -> None:
    network = record_python_execution_trace(network_probe)
    assert network.accepted_transition is False
    assert network.operational_acceptance is False
    effects = [
        event
        for event in network.events
        if event.event_kind == EventKind.EXTERNAL.value or event.payload.get("denied") is True
    ]
    assert effects
    assert any("socket" in str(event.payload.get("effect", "")) for event in effects)
    process = record_python_execution_trace(subprocess_probe)
    assert process.accepted_transition is False
    denied = [
        event
        for event in process.events
        if event.event_kind == EventKind.EXTERNAL.value or event.payload.get("denied") is True
    ]
    assert denied
    assert any("subprocess" in str(event.payload.get("effect", "")) for event in denied)


def test_deterministic_promised_replay_matches_under_exact_bindings() -> None:
    env = {"language": "python", "lane": "replay"}
    original = record_python_execution_trace(caller, environment_binding=env)
    replay = replay_deterministic_trace(
        original, subject=caller, kwargs=None
    )
    assert isinstance(replay, PythonExecutionReplayReceipt)
    assert replay.matched is True
    assert replay.binding_matched is True
    assert replay.original_trace_cid == replay.replayed_trace_cid
    assert replay.original_public_trace_cid == replay.replayed_public_trace_cid
    assert replay.original_event_cids == replay.replayed_event_cids
    assert replay.operational_acceptance is False
    assert original.accepted_transition is True
    assert replay.accepted_transition is True


def test_replay_of_cancelled_trace_never_accepts_a_transition() -> None:
    original = record_python_execution_trace(raise_cancel)
    replay = replay_deterministic_trace(original, subject=raise_cancel)
    assert original.accepted_transition is False
    assert replay.accepted_transition is False
    assert replay.original_outcome == CollectionOutcome.CANCELLED.value
    assert replay.replayed_outcome == CollectionOutcome.CANCELLED.value
    assert replay.matched is True


def test_replay_rejects_environment_drift_through_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    original = record_python_execution_trace(
        ping, environment_binding={"language": "python", "lane": "left"}
    )

    def drifted_record(subject, *args, **kwargs):  # type: ignore[no-untyped-def]
        return record_python_execution_trace(
            subject,
            *args,
            policy=kwargs.get("policy"),
            tree_cid=kwargs.get("tree_cid"),
            environment_binding={"language": "python", "lane": "right"},
            cancellation=kwargs.get("cancellation"),
        )

    import ipfs_datasets_py.logic.software_verification.python_execution_trace as mod

    monkeypatch.setattr(mod, "record_python_execution_trace", drifted_record)
    with pytest.raises(PythonExecutionTraceError, match="environment_binding_cid"):
        mod.replay_deterministic_trace(original, subject=ping)


def test_tracer_never_persists_operational_acceptance() -> None:
    record = record_python_execution_trace(ping)
    assert record.operational_acceptance is False
    assert record.receipt.operational_acceptance is False
    assert record.outcome == CollectionOutcome.COMPLETED.value
    assert record.accepted_transition is True
    for event in record.events:
        if event.observation_admissible:
            assert event.event_origin == "observed"


def test_non_callable_subject_fails_closed() -> None:
    with pytest.raises(PythonExecutionTraceError, match="callable"):
        record_python_execution_trace(None)  # type: ignore[arg-type]


def test_observations_exclude_unavailable_and_predicted_events() -> None:
    record = record_python_execution_trace(caller)
    assert record.observations
    observed_cids = {item.event_cid for item in record.observations}
    for event in record.events:
        if event.observation_admissible:
            assert event.program_event_cid in observed_cids
        else:
            assert event.program_event_cid not in observed_cids
