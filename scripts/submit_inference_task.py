#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit a text-generation task to the ipfs_datasets_py task queue")
    parser.add_argument("prompt")
    parser.add_argument("--model", default=os.environ.get("IPFS_DATASETS_PY_LLM_MODEL", "gpt2"))
    parser.add_argument(
        "--queue",
        default=os.environ.get(
            "IPFS_DATASETS_PY_TASK_QUEUE_PATH",
            os.path.join(os.path.expanduser("~"), ".cache", "ipfs_datasets_py", "task_queue.duckdb"),
        ),
    )
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.2)

    args = parser.parse_args()

    from ipfs_datasets_py import llm_router

    task_id = llm_router.submit_task(
        prompt=args.prompt,
        model_name=args.model,
        queue_path=args.queue,
        max_new_tokens=int(args.max_new_tokens),
        temperature=float(args.temperature),
    )

    print(task_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
