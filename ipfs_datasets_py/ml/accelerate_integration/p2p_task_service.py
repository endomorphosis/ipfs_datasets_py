"""libp2p RPC service for the TaskQueue.

This is a thin transport wrapper around the local SQLite-backed TaskQueue.
It enables other peers to submit tasks and wait for results.

Environment:
- IPFS_DATASETS_PY_TASK_P2P_LISTEN_PORT: TCP port to listen on (default: 9710)
- IPFS_DATASETS_PY_TASK_P2P_TOKEN: optional shared secret required in RPC messages

Protocol:
- Base protocol id: /ipfs-datasets/task-queue/1.0.0
- Each stream sends a single JSON request and receives a single JSON response.

Operations:
- op=submit: {task_type, model_name, payload}
- op=get: {task_id}
- op=wait: {task_id, timeout_s}

This module follows the same async `py-libp2p` patterns used by the cache
modules in this repo (await `new_host()`, `host.get_network().listen(...)`).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


def _have_libp2p() -> bool:
    try:
        import libp2p  # noqa: F401
        return True
    except Exception:
        return False


@dataclass
class ServiceConfig:
    listen_port: int = 9710


def _load_config() -> ServiceConfig:
    port = int(os.environ.get("IPFS_DATASETS_PY_TASK_P2P_LISTEN_PORT", "9710"))
    return ServiceConfig(listen_port=port)


async def serve_task_queue(*, queue_path: str, listen_port: Optional[int] = None) -> None:
    """Run the libp2p task queue service forever."""

    if not _have_libp2p():
        raise RuntimeError("libp2p is not installed; install ipfs_datasets_py[p2p]")

    import anyio
    from libp2p import new_host

    from .p2p_task_protocol import PROTOCOL_V1, auth_ok
    from .task_queue import TaskQueue

    cfg = _load_config()
    if listen_port is not None:
        cfg.listen_port = int(listen_port)

    queue = TaskQueue(queue_path)
    host = await new_host()

    async def _handle(stream) -> None:
        try:
            raw = await stream.read()
            if not raw:
                return
            try:
                msg = json.loads(raw.decode("utf-8"))
            except Exception:
                await stream.write(json.dumps({"ok": False, "error": "invalid_json"}).encode("utf-8"))
                return

            if not isinstance(msg, dict):
                await stream.write(json.dumps({"ok": False, "error": "invalid_message"}).encode("utf-8"))
                return

            if not auth_ok(msg):
                await stream.write(json.dumps({"ok": False, "error": "unauthorized"}).encode("utf-8"))
                return

            op = (msg.get("op") or "").strip().lower()

            if op == "submit":
                task_type = str(msg.get("task_type") or "text-generation")
                model_name = str(msg.get("model_name") or "")
                payload = msg.get("payload")
                if not isinstance(payload, dict):
                    payload = {"payload": payload}
                task_id = queue.submit(task_type=task_type, model_name=model_name, payload=payload)
                await stream.write(json.dumps({"ok": True, "task_id": task_id}).encode("utf-8"))
                return

            if op == "get":
                task_id = str(msg.get("task_id") or "")
                task = queue.get(task_id)
                await stream.write(json.dumps({"ok": True, "task": task}).encode("utf-8"))
                return

            if op == "wait":
                task_id = str(msg.get("task_id") or "")
                timeout_s = float(msg.get("timeout_s") or 60.0)
                deadline = time.time() + max(0.0, timeout_s)

                task = queue.get(task_id)
                while task is not None and task.get("status") in {"queued", "running"} and time.time() < deadline:
                    await trio.sleep(0.1)
                    task = queue.get(task_id)

                await stream.write(json.dumps({"ok": True, "task": task}).encode("utf-8"))
                return

            await stream.write(json.dumps({"ok": False, "error": "unknown_op"}).encode("utf-8"))
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    host.set_stream_handler(PROTOCOL_V1, _handle)

    listen_addr = f"/ip4/0.0.0.0/tcp/{cfg.listen_port}"
    await host.get_network().listen(listen_addr)

    peer_id = host.get_id().pretty()
    public_ip = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_PUBLIC_IP", "127.0.0.1").strip() or "127.0.0.1"
    announced = f"/ip4/{public_ip}/tcp/{cfg.listen_port}/p2p/{peer_id}"
    print(f"ipfs_datasets_py task queue p2p service started")
    print(f"peer_id={peer_id}")
    print(f"multiaddr={announced}")

    announce_file = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_ANNOUNCE_FILE", "").strip()
    if announce_file:
        try:
            os.makedirs(os.path.dirname(announce_file) or ".", exist_ok=True)
            with open(announce_file, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"peer_id": peer_id, "multiaddr": announced}, ensure_ascii=False))
        except Exception:
            pass

    while True:
        await anyio.sleep(3600)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run libp2p TaskQueue RPC service")
    parser.add_argument(
        "--queue",
        required=True,
        help="Path to task queue DuckDB file",
    )
    parser.add_argument("--listen-port", type=int, default=None)

    args = parser.parse_args(argv)

    import anyio

    anyio.run(serve_task_queue, queue_path=args.queue, listen_port=args.listen_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
