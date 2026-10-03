"""Explicit local queue ownership for artifact-bound CodebaseIR worker tasks.

This leaf does not start the generic worker, a service, discovery, or transport.
The injected handler owns artifact verification and bounded numerical work;
the injected guard owns source/model round liveness. Queue results are receipts,
never authority to register or promote a model or advance a source head.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable

from .task_queue import TaskQueue
from .worker_hooks import HookRegistry

TASK_TYPE = "codebase_ir.federated_artifact_update@1"
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 32 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN_FIELDS = {"queue_task_id", "queue_attempt", "worker_id", "request_sha256", "deadline_unix_s"}


class CodebaseDispatchError(RuntimeError):
    """A task request, owner guard, or live queue claim no longer agrees."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CodebaseDispatchError(message)


def _text(value: Any, name: str, maximum: int = 512) -> str:
    _require(type(value) is str and bool(value) and value == value.strip()
             and len(value.encode("utf-8")) <= maximum
             and all(ord(char) >= 32 and ord(char) != 127 for char in value),
             "invalid bounded " + name)
    return value


def _wire(value: Any, maximum: int) -> bytes:
    try:
        _json_types(value)
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise CodebaseDispatchError("bounded inert canonical JSON required") from exc
    _require(len(raw) <= maximum, "dispatch JSON exceeds its byte bound")
    return raw


def _json_types(value: Any) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        _require(math.isfinite(value), "finite native JSON numbers required")
        return
    if type(value) is list:
        for item in value:
            _json_types(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            _require(type(key) is str, "exact native JSON string keys required")
            _json_types(item)
        return
    raise CodebaseDispatchError("exact native JSON scalar/container types required")


def _copy(value: Any, maximum: int = MAX_RESULT_BYTES) -> Any:
    return json.loads(_wire(value, maximum))


def codebase_dispatch_request_sha256(payload: dict[str, Any], model_name: str) -> str:
    """Commit the complete task type, model identity, and artifact-only payload."""
    _require(type(payload) is dict, "exact dispatch payload mapping required")
    _text(model_name, "model_name")
    return hashlib.sha256(_wire({"task_type": TASK_TYPE, "model_name": model_name,
                               "payload": payload}, MAX_REQUEST_BYTES)).hexdigest()


def register_codebase_federated_handler(handler: Callable, *, registry: HookRegistry) -> str:
    """Register only on the explicitly supplied native hook registry."""
    _require(type(registry) is HookRegistry, "explicit native HookRegistry required")
    _require(callable(handler), "callable CodebaseIR handler required")
    return registry.register(TASK_TYPE, handler, source=__name__)


class CodebaseQueueDispatcher:
    """Drive one exact task through native local submit/claim/retry/complete.

    Queue attempt numbers and model round attempt/fence numbers are independent.
    A fresh UUID worker identity for every invocation fences old native claims,
    whose native mutations are guarded by worker identity rather than attempt.
    The handler must honor ``dispatch.deadline_unix_s`` through its existing
    bounded subprocess lifecycle. Long work can explicitly call ``heartbeat``.
    Completed receipts are replayed without renewing claims or invoking fitting.
    """

    def __init__(self, queue: TaskQueue, handler: Callable, *,
                 worker_id_prefix: str = "codebase-worker",
                 guard: Callable = lambda task: True, clock: Callable = time.time):
        _require(isinstance(queue, TaskQueue) and not queue._quack,
                 "already-created local native TaskQueue required")
        _require(callable(handler) and callable(guard) and callable(clock),
                 "callable handler, owner guard and clock required")
        self.queue, self.handler, self.guard, self.clock = queue, handler, guard, clock
        self.worker_id_prefix = _text(worker_id_prefix, "worker_id_prefix", 128)
        self._scoped_guards = ContextVar("codebase_dispatch_guards:" + uuid.uuid4().hex, default=())

    @contextmanager
    def scoped_guard(self, guard: Callable):
        """Layer a round-owner guard in this context without shared mutation."""
        _require(callable(guard), "callable scoped owner guard required")
        token = self._scoped_guards.set((*self._scoped_guards.get(), guard))
        try:
            yield self
        finally:
            self._scoped_guards.reset(token)

    def history(self, payload: dict, model_name: str, *, limit: int = 10000) -> dict | None:
        """Read an exact request within a bounded scoped queue inventory.

        Callers holding a sidecar task ID should prefer ``queue.get(task_id)``;
        this convenience scan returns None when the bounded inventory omits it.
        """
        request = codebase_dispatch_request_sha256(payload, model_name)
        _require(type(limit) is int and 1 <= limit <= 10000, "bounded history inventory required")
        for row in self.queue.list(task_types=[TASK_TYPE], limit=limit):
            if row.get("idempotency_key") == request:
                self._identity(row, payload, model_name, request)
                return _copy(row)
        return None

    def _now(self) -> float:
        value = self.clock()
        _require(type(value) in {int, float} and math.isfinite(value), "finite dispatch clock required")
        return float(value)

    @staticmethod
    def _duration(value: Any, name: str, *, minimum: float = 1) -> float:
        _require(type(value) in {int, float} and math.isfinite(value)
                 and value > 0 and minimum <= value <= 600,
                 "positive bounded " + name + " required")
        return float(value)

    def _identity(self, row: Any, payload: dict, model_name: str, request_sha256: str) -> None:
        _require(type(row) is dict and row.get("task_type") == TASK_TYPE
                 and row.get("model_name") == model_name
                 and _wire(row.get("payload"), MAX_REQUEST_BYTES) == _wire(payload, MAX_REQUEST_BYTES)
                 and codebase_dispatch_request_sha256(row["payload"], row["model_name"]) == request_sha256,
                 "persisted task differs from exact request commitment")

    def _task_for_token(self, token: dict) -> dict:
        _require(type(token) is dict and set(token) == _TOKEN_FIELDS,
                 "closed native queue attempt token required")
        _text(token["queue_task_id"], "queue_task_id")
        _text(token["worker_id"], "worker_id")
        _require(type(token["queue_attempt"]) is int and token["queue_attempt"] > 0
                 and type(token["request_sha256"]) is str and _SHA.fullmatch(token["request_sha256"])
                 and type(token["deadline_unix_s"]) in {int, float}
                 and math.isfinite(token["deadline_unix_s"]), "invalid native queue attempt token")
        row = self.queue.get(token["queue_task_id"])
        _require(type(row) is dict and row.get("task_type") == TASK_TYPE
                 and codebase_dispatch_request_sha256(row["payload"], row["model_name"]) == token["request_sha256"],
                 "queue attempt belongs to another exact request")
        now = self._now()
        _require(row["status"] == "running" and row["assigned_worker"] == token["worker_id"]
                 and row["attempt"] == token["queue_attempt"]
                 and type(row["lease_until"]) in {int, float} and math.isfinite(row["lease_until"])
                 and row["lease_until"] > now and token["deadline_unix_s"] > now,
                 "stale, expired or replaced native queue attempt")
        return {"task_id": row["task_id"], "task_type": TASK_TYPE, "model_name": row["model_name"],
                "payload": _copy(row["payload"], MAX_REQUEST_BYTES),
                "assigned_worker": token["worker_id"], "dispatch": _copy(token)}

    def _guard(self, task: dict) -> None:
        for guard in (self.guard, *self._scoped_guards.get()):
            _require(guard(_copy(task)) is True, "owner round guard rejected this source/model attempt or fence")

    def heartbeat(self, token: dict, *, lease_seconds: float = 300) -> bool:
        """Renew only this still-live exact queue attempt and owner round."""
        duration = self._duration(lease_seconds, "lease_seconds")
        task = self._task_for_token(token)
        self._guard(task)
        # The guard may itself have observed an owner change or consumed time.
        self._task_for_token(token)
        renewed = self.queue.heartbeat(task_id=token["queue_task_id"], worker_id=token["worker_id"],
                                       lease_seconds=duration, now=self._now())
        _require(renewed is True, "native queue rejected exact owner heartbeat")
        self._task_for_token(token)
        return True

    def dispatch(self, payload: dict[str, Any], model_name: str, *, request_sha256: str | None = None,
                 lease_seconds: float = 300, timeout_seconds: float = 300,
                 max_attempts: int = 3, retry_delay_seconds: float = 0) -> dict[str, Any]:
        """Submit once and return the exact retained result, or reject the claim.

        Handler errors release only a still-live owned claim using native retry.
        An owner guard rejection fails that live task. Expired/replaced claims
        cannot publish, fail, retry, or renew the newer attempt.
        """
        request = codebase_dispatch_request_sha256(payload, model_name)
        _require(request_sha256 is None or request_sha256 == request, "request SHA-256 differs from full task/model/payload")
        duration = self._duration(lease_seconds, "lease_seconds")
        timeout = self._duration(timeout_seconds, "timeout_seconds", minimum=0)
        _require(type(max_attempts) is int and 1 <= max_attempts <= 1000, "finite exact native retry bound required")
        _require(type(retry_delay_seconds) in {int, float} and math.isfinite(retry_delay_seconds)
                 and 0 <= retry_delay_seconds <= 600, "bounded native retry delay required")
        payload = _copy(payload, MAX_REQUEST_BYTES)
        task_id = self.queue.submit_once(idempotency_key=request, task_type=TASK_TYPE,
                                        model_name=model_name, payload=payload, max_attempts=max_attempts)
        row = self.queue.get(task_id)
        self._identity(row, payload, model_name, request)
        if row["status"] == "completed":
            _require(type(row["result"]) is dict, "completed queue task lacks a retained result")
            return _copy(row["result"])
        self.queue.recover_expired_leases(now=self._now())
        worker_id = self.worker_id_prefix + ":" + uuid.uuid4().hex
        claimed = self.queue.claim(task_id=task_id, worker_id=worker_id, lease_seconds=duration)
        if claimed is None:
            # Another live invocation may have completed between read and claim.
            settled = self.queue.get(task_id)
            self._identity(settled, payload, model_name, request)
            if settled["status"] == "completed":
                _require(type(settled["result"]) is dict, "completed queue task lacks a retained result")
                return _copy(settled["result"])
        _require(claimed is not None, "exact task is unavailable, already claimed, delayed or exhausted")
        token = {"queue_task_id": task_id, "queue_attempt": claimed.attempt, "worker_id": worker_id,
                 "request_sha256": request, "deadline_unix_s": self._now() + timeout}
        task = self._task_for_token(token)
        try:
            self._guard(task)
            task = self._task_for_token(token)
            result = self.handler(_copy(task))
            _require(type(result) is dict, "CodebaseIR handler must return an exact receipt mapping")
            result = _copy(result)
            task = self._task_for_token(token)
            self._guard(task)
            self._task_for_token(token)
        except Exception as exc:
            self._release_failure(token, exc, retry_delay_seconds)
            raise
        completed = self.queue.complete(task_id=task_id, status="completed", result=result, worker_id=worker_id)
        _require(completed is True, "native queue rejected exact owner completion")
        stored = self.queue.get(task_id)
        self._identity(stored, payload, model_name, request)
        _require(stored["status"] == "completed" and stored["assigned_worker"] == worker_id
                 and stored["attempt"] == token["queue_attempt"]
                 and _wire(stored["result"], MAX_RESULT_BYTES) == _wire(result, MAX_RESULT_BYTES),
                 "completed native queue outcome differs from this exact attempt receipt")
        return _copy(stored["result"])

    def _release_failure(self, token: dict, error: Exception, retry_delay: float) -> None:
        try:
            task = self._task_for_token(token)
        except CodebaseDispatchError:
            return
        message = str(error)[:2048]
        try:
            self._guard(task)
            live_owner = True
        except Exception:
            live_owner = False
        try:
            self._task_for_token(token)
        except CodebaseDispatchError:
            return
        if live_owner:
            released = self.queue.retry(task_id=token["queue_task_id"], worker_id=token["worker_id"],
                                        delay_seconds=retry_delay, error=message, now=self._now())
        else:
            released = self.queue.complete(task_id=token["queue_task_id"], worker_id=token["worker_id"],
                                           status="failed", error=message)
        _require(released is True, "native queue rejected exact owner failure release")


__all__ = ["TASK_TYPE", "CodebaseDispatchError", "CodebaseQueueDispatcher",
           "codebase_dispatch_request_sha256", "register_codebase_federated_handler"]
