"""Worker loop for accelerate task delegation.

Run as:
  python -m ipfs_datasets_py.ml.accelerate_integration.worker --queue /path/to.sqlite --worker-id worker-1

This is intentionally minimal and only supports `text-generation` tasks for now.
"""

from __future__ import annotations

import argparse
import threading
import time
from typing import Any, Dict, Optional

from .task_queue import TaskQueue


def _run_text_generation(task: Dict[str, Any]) -> Dict[str, Any]:
    # Import lazily to keep worker startup lightweight.
    from ipfs_datasets_py import llm_router

    model_name = str(task.get("model_name") or "")
    payload = task.get("payload") or {}
    prompt = payload.get("prompt") if isinstance(payload, dict) else payload

    text = llm_router.generate_text(
        str(prompt or ""),
        provider="accelerate",
        model_name=model_name or None,
        max_new_tokens=int(payload.get("max_new_tokens") or payload.get("max_tokens") or 128),
        temperature=float(payload.get("temperature") or 0.2),
    )
    return {"text": str(text)}


def run_worker(
    *,
    queue_path: str,
    worker_id: str,
    poll_interval_s: float = 0.5,
    once: bool = False,
    p2p_service: bool = False,
    p2p_listen_port: Optional[int] = None,
) -> int:
    if p2p_service:
        # Run the libp2p service in a background thread so the worker loop can
        # remain simple and blocking.
        def _run_service() -> None:
            try:
                import anyio
                from .p2p_task_service import serve_task_queue

                anyio.run(serve_task_queue, queue_path=queue_path, listen_port=p2p_listen_port)
            except Exception:
                # Best-effort: if libp2p isn't installed or fails, keep the local worker alive.
                return

        t = threading.Thread(target=_run_service, name=f"ipfs_datasets_p2p_task_service[{worker_id}]", daemon=True)
        t.start()

    queue = TaskQueue(queue_path)

    while True:
        task = queue.claim_next(worker_id=worker_id, supported_task_types=["text-generation"])
        if task is None:
            if once:
                return 0
            time.sleep(max(0.05, float(poll_interval_s)))
            continue

        try:
            if task.task_type in {"text-generation", "text_generation", "generation"}:
                result = _run_text_generation({
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "model_name": task.model_name,
                    "payload": task.payload,
                })
                queue.complete(task_id=task.task_id, status="completed", result=result)
            else:
                queue.complete(task_id=task.task_id, status="failed", error=f"Unsupported task_type: {task.task_type}")
        except Exception as exc:
            queue.complete(task_id=task.task_id, status="failed", error=str(exc))

        if once:
            return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ipfs_datasets_py accelerate task worker")
    parser.add_argument("--queue", dest="queue_path", required=True, help="Path to task queue DuckDB file")
    parser.add_argument("--worker-id", dest="worker_id", required=True, help="Worker identifier")
    parser.add_argument("--poll-interval-s", dest="poll_interval_s", type=float, default=0.5)
    parser.add_argument("--once", action="store_true", help="Process at most one task")
    parser.add_argument("--p2p-service", action="store_true", help="Also start a local libp2p TaskQueue RPC service")
    parser.add_argument("--p2p-listen-port", type=int, default=None, help="TCP port for libp2p service (default: env or 9710)")

    args = parser.parse_args(argv)
    return run_worker(
        queue_path=args.queue_path,
        worker_id=args.worker_id,
        poll_interval_s=float(args.poll_interval_s),
        once=bool(args.once),
        p2p_service=bool(args.p2p_service),
        p2p_listen_port=args.p2p_listen_port,
    )


if __name__ == "__main__":
    raise SystemExit(main())
