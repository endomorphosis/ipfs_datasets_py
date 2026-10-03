"""Actual local native queue qualification for scoped CodebaseIR dispatch."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import (
    TASK_TYPE, CodebaseDispatchError, CodebaseQueueDispatcher,
    codebase_dispatch_request_sha256, register_codebase_federated_handler,
)
from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_accelerate_py.p2p_tasks.worker_hooks import HookRegistry, get_registry


@pytest.fixture
def queue(tmp_path):
    native = TaskQueue(str(tmp_path / "codebase.duckdb"))
    try:
        yield native
    finally:
        native.close()


@pytest.fixture
def payload():
    return {"schema": "codebase-federated-artifact-request@1",
            "declaration": {"work_binding": {"client_id": "client-1", "attempt": 2, "fence": 7},
                            "artifacts": {"round": {"sha256": "a" * 64}}}}


def test_complete_replay_is_exact_and_survives_queue_restart(queue, payload):
    calls = []

    def handler(task):
        calls.append(task)
        return {"request_sha256": task["dispatch"]["request_sha256"],
                "update": {"cidv1": "retained-raw-update"}, "proof_authority": False}

    dispatcher = CodebaseQueueDispatcher(queue, handler)
    first = dispatcher.dispatch(payload, "codebase-model")
    token = calls[0]["dispatch"]
    assert token["queue_attempt"] == 1
    assert token["worker_id"].startswith("codebase-worker:")
    row = queue.get(token["queue_task_id"])
    assert row["attempt"] == 1 and row["assigned_worker"] == token["worker_id"]
    assert row["status"] == "completed" and row["result"] == first
    assert dispatcher.history(payload, "codebase-model") == row
    queue.close()
    reopened = TaskQueue(queue.path)
    try:
        replay = CodebaseQueueDispatcher(reopened, lambda task: pytest.fail("replayed fitting"))
        assert replay.dispatch(payload, "codebase-model") == first
        assert reopened.get(row["task_id"])["attempt"] == 1
    finally:
        reopened.close()
    assert len(calls) == 1


def test_hash_commits_type_model_and_complete_payload(queue, payload):
    expected = hashlib.sha256(json.dumps({"task_type": TASK_TYPE, "model_name": "model", "payload": payload},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()
    assert codebase_dispatch_request_sha256(payload, "model") == expected
    dispatcher = CodebaseQueueDispatcher(queue, lambda task: pytest.fail("wrong commitment executed"))
    with pytest.raises(CodebaseDispatchError, match="request SHA"):
        dispatcher.dispatch(payload, "model", request_sha256="0" * 64)
    assert queue.list() == []
    wrong = {**payload, "schema": "other-request"}
    queue.submit_once(idempotency_key=expected, task_type=TASK_TYPE, model_name="model", payload=wrong)
    with pytest.raises(ValueError, match="different work"):
        dispatcher.dispatch(payload, "model", request_sha256=expected)


@pytest.mark.parametrize("bad", [{1: "stringified-key"}, {"x": (1, 2)}, {"x": float("nan")}])
def test_non_native_or_nonfinite_json_is_rejected_before_submit(queue, bad):
    dispatcher = CodebaseQueueDispatcher(queue, lambda task: pytest.fail("bad JSON executed"))
    with pytest.raises(CodebaseDispatchError):
        dispatcher.dispatch(bad, "model")
    assert queue.list() == []


def test_only_one_concurrent_claim_invokes_handler(queue, payload):
    entered, release = threading.Event(), threading.Event()
    results, errors = [], []

    def handler(task):
        entered.set()
        assert release.wait(5)
        return {"ok": True}

    first = CodebaseQueueDispatcher(queue, handler)
    second = CodebaseQueueDispatcher(queue, lambda task: pytest.fail("concurrent fitting"))

    def execute():
        try:
            results.append(first.dispatch(payload, "model"))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(CodebaseDispatchError, match="unavailable"):
            second.dispatch(payload, "model")
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and not errors and results == [{"ok": True}]
    assert second.dispatch(payload, "model") == {"ok": True}


def test_expired_handler_result_cannot_complete_or_resurrect(queue, payload):
    clock = [time.time()]
    captured = []

    def handler(task):
        captured.append(task["dispatch"])
        clock[0] = queue.get(task["task_id"])["lease_until"] + 1
        return {"late": True}

    dispatcher = CodebaseQueueDispatcher(queue, handler, clock=lambda: clock[0])
    with pytest.raises(CodebaseDispatchError, match="expired"):
        dispatcher.dispatch(payload, "model", lease_seconds=1, timeout_seconds=5)
    token = captured[0]
    row = queue.get(token["queue_task_id"])
    assert row["status"] == "running" and row["result"] is None
    with pytest.raises(CodebaseDispatchError, match="expired"):
        dispatcher.heartbeat(token, lease_seconds=5)
    assert queue.get(row["task_id"])["lease_until"] == row["lease_until"]


def test_replaced_attempt_rejects_late_success_and_failure(queue, payload):
    captured = []

    def handler(task):
        captured.append(task["dispatch"])
        assert queue.retry(task_id=task["task_id"], worker_id=task["assigned_worker"])
        newer = queue.claim(task_id=task["task_id"], worker_id="other-invocation")
        assert newer.attempt == 2
        return {"stale": True}

    dispatcher = CodebaseQueueDispatcher(queue, handler)
    with pytest.raises(CodebaseDispatchError, match="replaced"):
        dispatcher.dispatch(payload, "model")
    row = queue.get(captured[0]["queue_task_id"])
    assert row["status"] == "running" and row["assigned_worker"] == "other-invocation"
    assert row["attempt"] == 2 and row["result"] is None
    with pytest.raises(CodebaseDispatchError, match="replaced"):
        dispatcher.heartbeat(captured[0])


def test_handler_cannot_extend_trusted_fractional_deadline_by_mutating_task(queue, payload):
    clock = [time.time()]
    captured = []

    def handler(task):
        captured.append(task["task_id"])
        clock[0] = task["dispatch"]["deadline_unix_s"] + .01
        task["dispatch"]["deadline_unix_s"] += 1000
        return {"late": True}

    dispatcher = CodebaseQueueDispatcher(queue, handler, clock=lambda: clock[0])
    with pytest.raises(CodebaseDispatchError, match="expired"):
        dispatcher.dispatch(payload, "model", lease_seconds=10, timeout_seconds=.05)
    row = queue.get(captured[0])
    assert row["status"] == "running" and row["result"] is None
    assert row["lease_until"] > clock[0]


def test_guard_rejection_before_handler_fails_only_owned_claim(queue, payload):
    dispatcher = CodebaseQueueDispatcher(queue, lambda task: pytest.fail("owner rejected before fitting"),
                                        guard=lambda task: False)
    with pytest.raises(CodebaseDispatchError, match="owner round"):
        dispatcher.dispatch(payload, "model")
    row = dispatcher.history(payload, "model")
    assert row["status"] == "failed" and row["attempt"] == 1 and row["lease_until"] is None


def test_scoped_guard_checks_after_handler_and_restores_context(queue, payload):
    live = [True]

    def handler(task):
        live[0] = False
        return {"should_not_publish": True}

    dispatcher = CodebaseQueueDispatcher(queue, handler)
    with dispatcher.scoped_guard(lambda task: live[0]):
        with pytest.raises(CodebaseDispatchError, match="owner round"):
            dispatcher.dispatch(payload, "model")
    assert dispatcher.history(payload, "model")["status"] == "failed"
    dispatcher.handler = lambda task: {"fresh": True}
    changed = {**payload, "schema": "second-request"}
    assert dispatcher.dispatch(changed, "model") == {"fresh": True}


def test_scoped_guards_do_not_leak_between_threads(queue, payload):
    dispatcher = CodebaseQueueDispatcher(queue, lambda task: {"ok": True})
    results, errors = [], []

    def execute():
        try:
            results.append(dispatcher.dispatch(payload, "model"))
        except Exception as exc:
            errors.append(exc)

    with dispatcher.scoped_guard(lambda task: False):
        thread = threading.Thread(target=execute)
        thread.start()
        thread.join(5)
    assert not thread.is_alive() and not errors and results == [{"ok": True}]


def test_handler_failure_uses_native_retry_backoff_and_unique_attempt(queue, payload):
    calls = []

    def handler(task):
        calls.append(task["dispatch"])
        if len(calls) == 1:
            raise RuntimeError("temporary numerical worker failure")
        return {"ok": True}

    dispatcher = CodebaseQueueDispatcher(queue, handler)
    with pytest.raises(RuntimeError, match="temporary"):
        dispatcher.dispatch(payload, "model", retry_delay_seconds=2)
    row = dispatcher.history(payload, "model")
    assert row["status"] == "queued" and row["attempt"] == 1
    assert row["assigned_worker"] is None and row["next_attempt_at"] > time.time()
    with pytest.raises(CodebaseDispatchError, match="delayed"):
        dispatcher.dispatch(payload, "model")
    # Advance native eligibility through the owned queue's persisted backoff.
    with queue._conn_lock:
        queue._get_conn().execute("UPDATE tasks SET next_attempt_at=0 WHERE task_id=?", [row["task_id"]])
    assert dispatcher.dispatch(payload, "model") == {"ok": True}
    assert calls[0]["worker_id"] != calls[1]["worker_id"] and calls[1]["queue_attempt"] == 2


def test_exhausted_native_attempts_do_not_refit(queue, payload):
    calls = []

    def handler(task):
        calls.append(task)
        raise RuntimeError("failed")

    dispatcher = CodebaseQueueDispatcher(queue, handler)
    with pytest.raises(RuntimeError):
        dispatcher.dispatch(payload, "model", max_attempts=1)
    assert dispatcher.history(payload, "model")["status"] == "failed"
    with pytest.raises(CodebaseDispatchError, match="exhausted"):
        dispatcher.dispatch(payload, "model", max_attempts=10)
    assert len(calls) == 1


def test_lost_completion_response_replays_native_result_without_handler(queue, payload, monkeypatch):
    calls = []
    dispatcher = CodebaseQueueDispatcher(queue, lambda task: calls.append(task) or {"persisted": True})
    native_complete = queue.complete

    def lose_response(**kwargs):
        assert native_complete(**kwargs)
        raise OSError("completion response lost")

    monkeypatch.setattr(queue, "complete", lose_response)
    with pytest.raises(OSError, match="response lost"):
        dispatcher.dispatch(payload, "model")
    assert dispatcher.dispatch(payload, "model") == {"persisted": True}
    assert len(calls) == 1


def test_completion_false_does_not_report_success(queue, payload, monkeypatch):
    dispatcher = CodebaseQueueDispatcher(queue, lambda task: {"ok": True})
    monkeypatch.setattr(queue, "complete", lambda **kwargs: False)
    with pytest.raises(CodebaseDispatchError, match="rejected exact owner completion"):
        dispatcher.dispatch(payload, "model")
    assert dispatcher.history(payload, "model")["status"] == "running"


def test_explicit_heartbeat_renews_native_owned_claim(queue, payload):
    captured = []
    dispatcher = None

    def handler(task):
        captured.append(task["dispatch"])
        before = queue.get(task["task_id"])["lease_until"]
        assert dispatcher.heartbeat(task["dispatch"], lease_seconds=10)
        assert queue.get(task["task_id"])["lease_until"] > before
        return {"ok": True}

    dispatcher = CodebaseQueueDispatcher(queue, handler)
    assert dispatcher.dispatch(payload, "model", lease_seconds=1, timeout_seconds=10) == {"ok": True}
    with pytest.raises(CodebaseDispatchError, match="stale"):
        dispatcher.heartbeat(captured[0])


def test_explicit_hook_registration_has_no_global_activation(queue):
    before = get_registry().snapshot()
    registry = HookRegistry()
    handler = lambda task: {"ok": True}
    dispatcher = CodebaseQueueDispatcher(queue, handler)
    assert dispatcher.handler is handler
    assert get_registry().snapshot() == before
    assert register_codebase_federated_handler(handler, registry=registry) == TASK_TYPE
    assert registry.snapshot()[TASK_TYPE].handler is handler
    assert get_registry().snapshot() == before


def test_import_and_instantiation_do_not_open_network_or_worker(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    script = """
import socket
def reject_socket(*args, **kwargs):
    raise AssertionError('network activated')
socket.socket = reject_socket
import sys
from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import CodebaseQueueDispatcher
from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
queue = TaskQueue(sys.argv[1])
CodebaseQueueDispatcher(queue, lambda task: {})
assert 'ipfs_accelerate_py.p2p_tasks.worker' not in sys.modules
assert 'ipfs_accelerate_py.p2p_tasks.service' not in sys.modules
assert 'ipfs_accelerate_py.p2p_tasks.client' not in sys.modules
queue.close()
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "import.duckdb")],
                            cwd=repository, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
