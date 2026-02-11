"""Compatibility wrapper for the libp2p TaskQueue RPC service.

The canonical implementation now lives in ``ipfs_accelerate_py.p2p_tasks`` so
systemd-deployed MCP services can reuse the same code.
"""

from __future__ import annotations

import importlib
from typing import Optional

async def serve_task_queue(*, queue_path: str, listen_port: Optional[int] = None) -> None:
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.service")
    a_serve_task_queue = getattr(module, "serve_task_queue")
    await a_serve_task_queue(queue_path=queue_path, listen_port=listen_port)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import anyio

    parser = argparse.ArgumentParser(description="Run libp2p TaskQueue RPC service")
    parser.add_argument("--queue", required=True, help="Path to task queue DuckDB file")
    parser.add_argument("--listen-port", type=int, default=None)

    args = parser.parse_args(argv)

    async def _main() -> None:
        await serve_task_queue(queue_path=args.queue, listen_port=args.listen_port)

    anyio.run(_main, backend="trio")
    return 0


__all__ = ["serve_task_queue", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
