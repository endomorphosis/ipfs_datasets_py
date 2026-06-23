#!/usr/bin/env python3
"""Seed Codex repair TODOs from failed-validation clusters in an existing queue."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    ModalTodoQueue,
    ModalTodoSupervisor,
)


@contextmanager
def _queue_file_lock(queue_path: Path) -> Iterator[None]:
    lock_path = queue_path.with_suffix(queue_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _role_counts(queue: ModalTodoQueue) -> dict[str, Any]:
    return {
        "role_status_counts": queue.role_status_counts(),
        "status_counts": queue.status_counts(),
    }


def seed_failed_validation_rescues(
    queue_path: Path,
    *,
    max_clusters: int,
    rescue_max_attempts: int,
    program_synthesis_scope: str | None,
    failure_reason: str | None,
    original_action: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    with _queue_file_lock(queue_path):
        queue = ModalTodoQueue.load_jsonl(queue_path)
        before = _role_counts(queue)
        supervisor = ModalTodoSupervisor(queue=queue)
        before_ids = {todo.todo_id for todo in supervisor.queue.all()}
        seeded = supervisor.seed_failed_validation_rescue_todos(
            max_clusters=max_clusters,
            rescue_max_attempts=rescue_max_attempts,
            program_synthesis_scope=program_synthesis_scope,
            failure_reason=failure_reason,
            original_action=original_action,
        )
        seeded_ids = [
            todo.todo_id
            for todo in seeded
            if todo.todo_id not in before_ids
            and supervisor.queue.get(todo.todo_id) is not None
        ]
        if not dry_run and seeded_ids:
            supervisor.queue.save_jsonl(queue_path)
        return {
            "after": _role_counts(supervisor.queue),
            "before": before,
            "deduped_count": int(supervisor.last_program_synthesis_deduped_count),
            "dry_run": bool(dry_run),
            "queue_path": str(queue_path),
            "rescue_max_attempts": int(rescue_max_attempts),
            "seeded_count": len(seeded_ids),
            "seeded_todo_ids": seeded_ids,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue_path", type=Path, help="Modal TODO queue JSONL path.")
    parser.add_argument(
        "--max-clusters",
        type=int,
        default=8,
        help="Maximum failed-validation clusters to convert into rescue TODOs.",
    )
    parser.add_argument(
        "--rescue-max-attempts",
        type=int,
        default=4,
        help="Maximum rescue attempts per failed-validation cluster.",
    )
    parser.add_argument(
        "--program-synthesis-scope",
        default=None,
        help="Optional scope filter, e.g. ir_decompiler or compiler_registry.",
    )
    parser.add_argument(
        "--failure-reason",
        default=None,
        help="Optional failed-validation reason filter.",
    )
    parser.add_argument(
        "--original-action",
        default=None,
        help="Optional failed TODO action filter.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not save changes.")
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    args = parser.parse_args(argv)

    report = seed_failed_validation_rescues(
        args.queue_path,
        max_clusters=args.max_clusters,
        rescue_max_attempts=args.rescue_max_attempts,
        program_synthesis_scope=args.program_synthesis_scope,
        failure_reason=args.failure_reason,
        original_action=args.original_action,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print(f"queue={report['queue_path']}")
    print(f"dry_run={report['dry_run']}")
    print(f"seeded_count={report['seeded_count']}")
    print(f"deduped_count={report['deduped_count']}")
    if report["seeded_todo_ids"]:
        print("seeded_todo_ids=" + ",".join(report["seeded_todo_ids"]))
    print("before=" + json.dumps(report["before"], sort_keys=True))
    print("after=" + json.dumps(report["after"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
