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

    args = parser.parse_args()

    from ipfs_datasets_py.ml.accelerate_integration.p2p_task_service import main as svc_main

    return svc_main(["--queue", args.queue, "--listen-port", str(args.listen_port)])


if __name__ == "__main__":
    raise SystemExit(main())
