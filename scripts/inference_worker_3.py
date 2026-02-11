#!/usr/bin/env python3

from __future__ import annotations

import os
import sys


def main() -> int:
    queue_path = os.environ.get(
        "IPFS_DATASETS_PY_TASK_QUEUE_PATH",
        os.path.join(os.path.expanduser("~"), ".cache", "ipfs_datasets_py", "task_queue.duckdb"),
    )

    p2p_enable = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}
    if p2p_enable and not os.environ.get("IPFS_DATASETS_PY_TASK_P2P_LISTEN_PORT"):
        os.environ["IPFS_DATASETS_PY_TASK_P2P_LISTEN_PORT"] = "9712"

    from ipfs_datasets_py.ml.accelerate_integration.worker import run_worker

    return run_worker(queue_path=queue_path, worker_id="worker-3", p2p_service=bool(p2p_enable))


if __name__ == "__main__":
    raise SystemExit(main())
