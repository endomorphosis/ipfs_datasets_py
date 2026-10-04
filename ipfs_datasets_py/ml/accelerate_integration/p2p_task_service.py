"""Compatibility wrapper for the libp2p TaskQueue RPC service.

The canonical implementation now lives in ``ipfs_accelerate_py.p2p_tasks`` so
systemd-deployed MCP services can reuse the same code.
"""

from __future__ import annotations

import importlib
import os
from typing import Optional


def _set_discovery_env(
    *,
    p2p_dht: Optional[bool] = None,
    p2p_rendezvous: Optional[bool] = None,
    p2p_rendezvous_ns: Optional[str] = None,
    p2p_autonat: Optional[bool] = None,
) -> None:
    def _set_bool(name: str, value: Optional[bool]) -> None:
        if value is None:
            return
        os.environ[name] = "1" if bool(value) else "0"

    def _set_str(name: str, value: Optional[str]) -> None:
        if value is None:
            return
        text = str(value)
        if text:
            os.environ[name] = text

    # Set both prefixes for compatibility.
    for prefix in ("IPFS_ACCELERATE_PY_", "IPFS_DATASETS_PY_"):
        _set_bool(f"{prefix}TASK_P2P_DHT", p2p_dht)
        _set_bool(f"{prefix}TASK_P2P_RENDEZVOUS", p2p_rendezvous)
        _set_bool(f"{prefix}TASK_P2P_AUTONAT", p2p_autonat)
        _set_str(f"{prefix}TASK_P2P_RENDEZVOUS_NS", p2p_rendezvous_ns)


async def serve_task_queue(
    *,
    queue_path: str,
    listen_port: Optional[int] = None,
    p2p_dht: Optional[bool] = None,
    p2p_rendezvous: Optional[bool] = None,
    p2p_rendezvous_ns: Optional[str] = None,
    p2p_autonat: Optional[bool] = None,
) -> None:
    _set_discovery_env(
        p2p_dht=p2p_dht,
        p2p_rendezvous=p2p_rendezvous,
        p2p_rendezvous_ns=p2p_rendezvous_ns,
        p2p_autonat=p2p_autonat,
    )
    module = importlib.import_module("ipfs_accelerate_py.p2p_tasks.service")
    a_serve_task_queue = getattr(module, "serve_task_queue")
    await a_serve_task_queue(queue_path=queue_path, listen_port=listen_port)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import anyio

    parser = argparse.ArgumentParser(description="Run libp2p TaskQueue RPC service")
    parser.add_argument("--queue", required=True, help="Path to task queue DuckDB file")
    parser.add_argument("--listen-port", type=int, default=None)
    parser.add_argument(
        "--p2p-dht",
        dest="p2p_dht",
        action="store_true",
        help="Enable libp2p DHT discovery (default: enabled; flag is optional)",
    )
    parser.add_argument(
        "--no-p2p-dht",
        dest="p2p_dht",
        action="store_false",
        help="Disable libp2p DHT discovery",
    )
    parser.set_defaults(p2p_dht=None)
    parser.add_argument(
        "--p2p-rendezvous",
        dest="p2p_rendezvous",
        action="store_true",
        help="Enable rendezvous discovery (default: enabled; flag is optional)",
    )
    parser.add_argument(
        "--no-p2p-rendezvous",
        dest="p2p_rendezvous",
        action="store_false",
        help="Disable rendezvous discovery",
    )
    parser.set_defaults(p2p_rendezvous=None)
    parser.add_argument(
        "--p2p-rendezvous-ns",
        dest="p2p_rendezvous_ns",
        default=None,
        help="Rendezvous namespace (default: ipfs-accelerate-task-queue)",
    )
    parser.add_argument(
        "--p2p-autonat",
        dest="p2p_autonat",
        action="store_true",
        help="Enable AutoNAT (default: enabled; flag is optional)",
    )
    parser.add_argument(
        "--no-p2p-autonat",
        dest="p2p_autonat",
        action="store_false",
        help="Disable AutoNAT",
    )
    parser.set_defaults(p2p_autonat=None)

    args = parser.parse_args(argv)

    async def _main() -> None:
        await serve_task_queue(
            queue_path=args.queue,
            listen_port=args.listen_port,
            p2p_dht=args.p2p_dht,
            p2p_rendezvous=args.p2p_rendezvous,
            p2p_rendezvous_ns=args.p2p_rendezvous_ns,
            p2p_autonat=args.p2p_autonat,
        )

    anyio.run(_main, backend="trio")
    return 0


__all__ = ["serve_task_queue", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
