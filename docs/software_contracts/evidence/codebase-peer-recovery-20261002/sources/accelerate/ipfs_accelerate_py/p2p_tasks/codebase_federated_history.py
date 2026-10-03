"""Exact read-only recovery of retained local CodebaseIR queue requests.

The queue already maintains a unique idempotency index. This leaf reads that
identity directly without submitting work or scanning the queue inventory.
The returned native row is evidence; callers still verify worker artifacts,
source/model lineage and the committed round before recovering provenance.
"""
from __future__ import annotations

import re
from typing import Any

from .codebase_federated_dispatch import (
    TASK_TYPE, MAX_REQUEST_BYTES, CodebaseDispatchError,
    _copy, _require, _text, _wire, codebase_dispatch_request_sha256,
)
from .task_queue import TaskQueue

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ROW_FIELDS = {
    "task_id", "task_type", "model_name", "payload", "status", "assigned_worker",
    "created_at", "updated_at", "result", "error", "priority", "attempt", "max_attempts",
    "next_attempt_at", "lease_until", "heartbeat_at", "idempotency_key",
}


def find_codebase_federated_task(queue: TaskQueue, *, request_sha256: str,
                                payload: dict[str, Any], model_name: str) -> dict | None:
    """Read one exact retained request using the native idempotency index.

    Missing work returns ``None`` and does not create a queue row. This helper
    accepts an already-open local native queue. It changes neither its schema
    nor task state and activates no worker, transport, admission or promotion.
    A task deleted or rebound between the indexed read and native ``get`` is
    rejected. Callers requiring a completed result must check the returned
    native status and validate the result against their committed model.
    """
    _require(type(queue) is TaskQueue and not queue._quack,
             "already-created local native TaskQueue required")
    _require(type(request_sha256) is str and _SHA.fullmatch(request_sha256) is not None,
             "exact lowercase request SHA-256 required")
    _require(type(payload) is dict, "exact dispatch payload mapping required")
    # Own the request before reading: neither a caller mutation nor a queued
    # JSON coercion may change the identity being recovered.
    payload = _copy(payload, MAX_REQUEST_BYTES)
    _require(codebase_dispatch_request_sha256(payload, model_name) == request_sha256,
             "request SHA-256 differs from full task/model/payload")
    with queue._conn_lock:
        connection = queue._connect()
        try:
            rows = connection.execute(
                "SELECT task_id FROM tasks WHERE idempotency_key=? LIMIT 2",
                (request_sha256,),
            ).fetchall()
        finally:
            connection.close()
        _require(len(rows) <= 1, "duplicate native request identities")
        if not rows:
            return None
        _require(len(rows[0]) == 1, "closed native identity lookup required")
        task_id = _text(rows[0][0], "task_id")
        try:
            row = queue.get(task_id)
        except (TypeError, ValueError, RecursionError) as exc:
            raise CodebaseDispatchError("indexed native task row is malformed") from exc
        _require(type(row) is dict and set(row) == _ROW_FIELDS
                 and row["task_id"] == task_id and row["idempotency_key"] == request_sha256,
                 "indexed native task disappeared or changed identity")
        _require(row["task_type"] == TASK_TYPE and row["model_name"] == model_name
                 and type(row["payload"]) is dict
                 and _wire(row["payload"], MAX_REQUEST_BYTES) == _wire(payload, MAX_REQUEST_BYTES)
                 and codebase_dispatch_request_sha256(row["payload"], row["model_name"]) == request_sha256,
                 "indexed native task differs from exact request scope")
        return _copy(row)


__all__ = ["find_codebase_federated_task"]
