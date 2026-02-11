#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ipfs_datasets_py TaskQueue libp2p RPC service")
    parser.add_argument(
        "--queue",
        default=os.environ.get(
            "IPFS_DATASETS_PY_TASK_QUEUE_PATH",
            os.path.join(os.path.expanduser("~"), ".cache", "ipfs_datasets_py", "task_queue.duckdb"),
        ),
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=int(os.environ.get("IPFS_DATASETS_PY_TASK_P2P_LISTEN_PORT", "9710")),
    )
    parser.add_argument("--no-p2p-dht", dest="p2p_dht", action="store_false", help="Disable libp2p DHT discovery")
    parser.set_defaults(p2p_dht=None)
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
    parser.add_argument("--no-p2p-autonat", dest="p2p_autonat", action="store_false", help="Disable AutoNAT")
    parser.set_defaults(p2p_autonat=None)

    args = parser.parse_args()

    from ipfs_datasets_py.ml.accelerate_integration.p2p_task_service import main as svc_main

    argv = ["--queue", args.queue, "--listen-port", str(args.listen_port)]
    if args.p2p_dht is False:
        argv.append("--no-p2p-dht")
    if args.p2p_rendezvous is False:
        argv.append("--no-p2p-rendezvous")
    if args.p2p_rendezvous_ns:
        argv.extend(["--p2p-rendezvous-ns", str(args.p2p_rendezvous_ns)])
    if args.p2p_autonat is False:
        argv.append("--no-p2p-autonat")

    return svc_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
