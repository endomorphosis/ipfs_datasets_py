"""Task queue used by the accelerate integration.

This is a lightweight, dependency-minimal task delegation mechanism intended to
support a "3 worker" pattern for distributed-style inference.

It intentionally does NOT require a live libp2p network. The transport layer can
be swapped later (e.g., libp2p pubsub / IPFS Kit). The local persistence layer is
DuckDB so the same queue file can be used for analytics/debugging.

Schema is stable and backwards compatible.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class QueuedTask:
    task_id: str
    task_type: str
    model_name: str
    payload: Dict[str, Any]
    created_at: float
    status: str
    assigned_worker: Optional[str] = None


def default_queue_path() -> str:
    return os.environ.get(
        "IPFS_DATASETS_PY_TASK_QUEUE_PATH",
        os.path.join(os.path.expanduser("~"), ".cache", "ipfs_datasets_py", "task_queue.duckdb"),
    )


class TaskQueue:
    """DuckDB-backed task queue.

    Concurrency model:
    - multiple workers may poll concurrently
    - claiming uses an atomic UPDATE guarded by a transaction
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or default_queue_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._init_db()

    def _connect(self):
        try:
            import duckdb  # type: ignore
        except Exception as exc:
            raise RuntimeError("duckdb is required for TaskQueue") from exc

        # DuckDB manages file locking internally; we open short-lived connections.
        return duckdb.connect(self.path)

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id VARCHAR PRIMARY KEY,
                    task_type VARCHAR NOT NULL,
                    model_name VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    assigned_worker VARCHAR,
                    created_at DOUBLE NOT NULL,
                    updated_at DOUBLE NOT NULL,
                    result_json VARCHAR,
                    error VARCHAR
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at)")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def submit(
        self,
        *,
        task_type: str,
        model_name: str,
        payload: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> str:
        tid = task_id or uuid.uuid4().hex
        now = time.time()
        payload_json = json.dumps(payload, sort_keys=True)

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO tasks(task_id, task_type, model_name, payload_json, status, assigned_worker, created_at, updated_at)
                VALUES(?, ?, ?, ?, 'queued', NULL, ?, ?)
                """,
                (tid, str(task_type), str(model_name), payload_json, now, now),
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return tid

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        if not task_id:
            return None

        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if row is None:
            return None

        # DuckDB returns tuples from fetchone()
        (
            _task_id,
            task_type,
            model_name,
            payload_json,
            status,
            assigned_worker,
            created_at,
            updated_at,
            result_json,
            error,
        ) = row

        result = None
        if isinstance(result_json, str) and result_json:
            try:
                result = json.loads(result_json)
            except Exception:
                result = result_json
        return {
            "task_id": _task_id,
            "task_type": task_type,
            "model_name": model_name,
            "payload": json.loads(payload_json),
            "status": status,
            "assigned_worker": assigned_worker,
            "created_at": created_at,
            "updated_at": updated_at,
            "result": result,
            "error": error,
        }

    def claim_next(
        self,
        *,
        worker_id: str,
        supported_task_types: Optional[Iterable[str]] = None,
    ) -> Optional[QueuedTask]:
        """Claim the next queued task.

        Returns a QueuedTask or None if no tasks are available.
        """

        if not worker_id:
            raise ValueError("worker_id is required")

        task_types = [t for t in (supported_task_types or []) if isinstance(t, str) and t.strip()]
        now = time.time()

        conn = self._connect()
        try:
            conn.execute("BEGIN TRANSACTION")

            if task_types:
                placeholders = ",".join(["?"] * len(task_types))
                row = conn.execute(
                    f"SELECT task_id FROM tasks WHERE status='queued' AND task_type IN ({placeholders}) ORDER BY created_at ASC LIMIT 1",
                    tuple(task_types),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT task_id FROM tasks WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
                ).fetchone()

            if row is None:
                conn.execute("COMMIT")
                return None

            task_id = str(row[0])
            conn.execute(
                """
                UPDATE tasks
                SET status='running', assigned_worker=?, updated_at=?
                WHERE task_id=? AND status='queued'
                """,
                (str(worker_id), now, task_id),
            )

            # DuckDB's rowcount is not reliable; verify by reading back.
            row2 = conn.execute(
                "SELECT * FROM tasks WHERE task_id=? AND status='running' AND assigned_worker=?",
                (task_id, str(worker_id)),
            ).fetchone()
            if row2 is None:
                conn.execute("COMMIT")
                return None

            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if row2 is None:
            return None

        try:
            payload = json.loads(row2[3])
        except Exception:
            payload = {"raw": row2[3]}

        return QueuedTask(
            task_id=str(row2[0]),
            task_type=str(row2[1]),
            model_name=str(row2[2]),
            payload=payload if isinstance(payload, dict) else {"payload": payload},
            created_at=float(row2[6]),
            status=str(row2[4]),
            assigned_worker=str(row2[5]) if row2[5] else None,
        )

    def complete(
        self,
        *,
        task_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> bool:
        if not task_id:
            return False
        status_norm = (status or "").strip().lower()
        if status_norm not in {"completed", "failed", "cancelled"}:
            raise ValueError("status must be one of: completed, failed, cancelled")

        now = time.time()
        result_json = json.dumps(result, sort_keys=True) if isinstance(result, dict) else None

        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE tasks
                SET status=?, result_json=?, error=?, updated_at=?
                WHERE task_id=?
                """,
                (status_norm, result_json, error, now, str(task_id)),
            )

            row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (str(task_id),)).fetchone()
            return bool(row and str(row[0]) == status_norm)
        finally:
            try:
                conn.close()
            except Exception:
                pass
