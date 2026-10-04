#!/usr/bin/env python3
"""Backfill deterministic Leanstral feedback metadata on an existing TODO queue."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    ModalTodoQueue,
    ModalTodoSupervisor,
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue_path", help="Modal TODO queue JSONL file to inspect.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist metadata changes back to the queue file.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    queue_path = Path(args.queue_path).expanduser()
    if not queue_path.is_file():
        raise FileNotFoundError(str(queue_path))
    queue = ModalTodoQueue.load_jsonl(queue_path)
    supervisor = ModalTodoSupervisor(queue=queue)
    report = supervisor.backfill_leanstral_patch_feedback_evidence()
    report["path"] = str(queue_path)
    report["write"] = bool(args.write)
    if args.write and int(report.get("updated_count", 0) or 0) > 0:
        supervisor.queue.save_jsonl(queue_path)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    raise SystemExit(main())
