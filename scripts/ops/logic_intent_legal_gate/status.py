#!/usr/bin/env python3
"""Operator status for the LIG multi-lane supervisor + merge train.

Surfaces shard health, projected task statuses (including merge-queued), and
the target-scoped merge-queue summary without mutating the protected board.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return int(text.split()[0])
    except ValueError:
        return None


def _parse_board_statuses(todo_path: Path, prefix: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not todo_path.is_file():
        return counts
    try:
        text = todo_path.read_text(encoding="utf-8")
    except OSError:
        return counts
    header_re = re.compile(rf"^##\s+({re.escape(prefix)}\d+)\b", re.M)
    status_re = re.compile(r"^- Status:\s*(\S+)", re.M | re.I)
    positions = [(m.start(), m.group(1)) for m in header_re.finditer(text)]
    for index, (start, _task_id) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        block = text[start:end]
        match = status_re.search(block)
        status = (match.group(1) if match else "unknown").lower()
        counts[status] += 1
    return counts


def _shard_rows(state_root: Path, shard_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for shard in range(shard_count):
        shard_dir = state_root / "shards" / str(shard)
        state_dir = shard_dir / "state"
        # Prefer lig_shard_* naming; fall back to any *_task_state.json.
        candidates = sorted(state_dir.glob("lig_shard_*_task_state.json"))
        if not candidates:
            candidates = sorted(state_dir.glob("*_task_state.json"))
        state_path = candidates[0] if candidates else state_dir / "task_state.json"
        state = _load_json(state_path) or {}
        supervisor_pid = _read_pid_file(shard_dir / "supervisor.pid")
        managed_pids = [
            _read_pid_file(path)
            for path in sorted(state_dir.glob("*_managed_daemon.pid"))
        ]
        managed_pids = [pid for pid in managed_pids if pid is not None]
        status_counts = Counter(
            str(value).lower()
            for value in (state.get("task_statuses") or {}).values()
            if str(value).strip()
        )
        rows.append(
            {
                "shard": shard,
                "state_path": str(state_path) if state_path.is_file() else "",
                "supervisor_pid": supervisor_pid,
                "supervisor_alive": bool(
                    supervisor_pid and _pid_alive(int(supervisor_pid))
                ),
                "managed_daemon_pids": managed_pids,
                "managed_daemon_alive": [
                    bool(pid and _pid_alive(int(pid))) for pid in managed_pids
                ],
                "active_task_id": str(state.get("active_task_id") or ""),
                "active_phase": str(state.get("active_phase") or ""),
                "active_attempt": state.get("active_attempt") or 0,
                "heartbeat_at": str(state.get("heartbeat_at") or ""),
                "last_progress_at": str(state.get("last_progress_at") or ""),
                "completed_count": int(state.get("completed_count") or 0),
                "ready_count": int(state.get("ready_count") or 0),
                "waiting_count": int(state.get("waiting_count") or 0),
                "blocked_count": int(state.get("blocked_count") or 0),
                "ready_task_ids": list(state.get("ready_task_ids") or [])[:20],
                "waiting_task_ids": list(state.get("waiting_task_ids") or [])[:30],
                "status_counts": dict(status_counts),
                "merge_queued_task_ids": sorted(
                    task_id
                    for task_id, status in (state.get("task_statuses") or {}).items()
                    if str(status).lower() == "merge-queued"
                ),
                "last_implementation_task_id": str(
                    state.get("last_implementation_task_id") or ""
                ),
                "last_implementation_commit": str(
                    state.get("last_implementation_commit") or ""
                )[:12],
                "last_implementation_branch": str(
                    state.get("last_implementation_branch") or ""
                ),
                "last_merge_error": str(state.get("last_merge_error") or "")[:200],
            }
        )
    return rows


def _merge_queue_status(
    *,
    repo_root: Path,
    merge_target_branch: str,
    merge_queue_dir: Path | None,
) -> dict[str, Any]:
    try:
        from ipfs_accelerate_py.agent_supervisor.merge.checkout_lock import (
            checkout_repository_id,
            merge_target_queue_dir,
        )
        from ipfs_accelerate_py.agent_supervisor.merge.merge_queue import MergeQueue
    except Exception as exc:  # pragma: no cover - import environment
        return {
            "available": False,
            "error": f"import_failed: {type(exc).__name__}: {exc}",
        }

    branch = str(merge_target_branch or "").strip() or "main"
    try:
        queue_dir = Path(merge_queue_dir) if merge_queue_dir else merge_target_queue_dir(
            repo_root, branch
        )
        repository_id = checkout_repository_id(repo_root)
        queue = MergeQueue(queue_dir)
        queue.bind_target(repository_id, branch, required=True)
        status = queue.status()
        active_cids = sorted(queue.active_canonical_task_ids())
        completed_cids = sorted(queue.completed_canonical_task_ids())
        return {
            "available": True,
            "queue_dir": str(queue_dir),
            "target_branch": branch,
            "target_repository_id": repository_id,
            "pending_count": int(queue.pending_count()),
            "processing_count": int(queue.processing_count()),
            "active_canonical_task_ids": active_cids[:50],
            "completed_canonical_task_ids": completed_cids[:50],
            "active_count": len(active_cids),
            "completed_count": len(completed_cids),
            "status": status,
        }
    except Exception as exc:
        return {
            "available": False,
            "target_branch": branch,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _git_branch_tip(repo_root: Path, branch: str) -> dict[str, Any]:
    result: dict[str, Any] = {"branch": branch, "exists": False, "tip": ""}
    if not branch:
        return result
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", branch],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return result
    tip = subprocess.run(
        ["git", "rev-parse", "--short", branch],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    result["exists"] = True
    result["tip"] = (tip.stdout or "").strip()
    return result


def _print_human(report: Mapping[str, Any]) -> None:
    print(f"LIG operator status @ {report.get('as_of')}")
    print(f"repo: {report.get('repo_root')}")
    print(
        f"merge_target: {report.get('merge_target_branch')} "
        f"tip={report.get('merge_target_tip', {}).get('tip') or '(missing)'} "
        f"exists={report.get('merge_target_tip', {}).get('exists')}"
    )
    print(f"todo: {report.get('todo_path')}")
    board = report.get("board_status_counts") or {}
    if board:
        board_bits = ", ".join(f"{k}={v}" for k, v in sorted(board.items()))
        print(f"board statuses: {board_bits}")
    print()
    print("=== shards ===")
    for row in report.get("shards") or []:
        alive = "up" if row.get("supervisor_alive") else "down"
        print(
            f"shard {row['shard']}: supervisor={row.get('supervisor_pid') or '-'}[{alive}] "
            f"active={row.get('active_task_id') or '-'} phase={row.get('active_phase') or '-'} "
            f"attempt={row.get('active_attempt')} "
            f"ready={row.get('ready_count')} waiting={row.get('waiting_count')} "
            f"blocked={row.get('blocked_count')} completed={row.get('completed_count')}"
        )
        mq = row.get("merge_queued_task_ids") or []
        if mq:
            print(f"  merge-queued: {', '.join(mq)}")
        if row.get("last_implementation_task_id"):
            print(
                f"  last_impl: {row.get('last_implementation_task_id')} "
                f"commit={row.get('last_implementation_commit') or '-'} "
                f"branch={row.get('last_implementation_branch') or '-'}"
            )
        if row.get("last_merge_error"):
            print(f"  last_merge_error: {row.get('last_merge_error')}")
        sc = row.get("status_counts") or {}
        if sc:
            print(
                "  projected: "
                + ", ".join(f"{k}={v}" for k, v in sorted(sc.items()))
            )
    print()
    print("=== merge train ===")
    mq = report.get("merge_queue") or {}
    if not mq.get("available"):
        print(f"unavailable: {mq.get('error') or 'unknown'}")
        return
    print(f"queue_dir: {mq.get('queue_dir')}")
    print(
        f"target={mq.get('target_branch')} pending={mq.get('pending_count')} "
        f"processing={mq.get('processing_count')} "
        f"active_ids={mq.get('active_count')} completed_ids={mq.get('completed_count')}"
    )
    status = mq.get("status") or {}
    if isinstance(status, dict):
        # Keep output bounded; show top-level counters when present.
        for key in (
            "pending",
            "processing",
            "completed",
            "quarantined",
            "cancelled",
            "failed",
            "merge_debt",
            "active",
        ):
            if key in status:
                print(f"  {key}: {status[key]}")
    active = mq.get("active_canonical_task_ids") or []
    if active:
        print(f"  active_cids (first {min(10, len(active))}):")
        for cid in active[:10]:
            print(f"    - {cid}")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    state_root = Path(args.state_root)
    if not state_root.is_absolute():
        state_root = (repo_root / state_root).resolve()
    todo_path = Path(args.todo_path)
    if not todo_path.is_absolute():
        todo_path = (repo_root / todo_path).resolve()
    merge_queue_dir = (
        Path(args.merge_queue_dir).resolve() if args.merge_queue_dir else None
    )

    shards = _shard_rows(state_root, int(args.shard_count))
    merge_queue = _merge_queue_status(
        repo_root=repo_root,
        merge_target_branch=str(args.merge_target_branch),
        merge_queue_dir=merge_queue_dir,
    )
    board_counts = _parse_board_statuses(todo_path, str(args.task_prefix))
    return {
        "schema": "ipfs_datasets_py/ops/logic-intent-legal-gate-status@1",
        "as_of": _utc_now(),
        "repo_root": str(repo_root),
        "state_root": str(state_root),
        "todo_path": str(todo_path),
        "task_prefix": str(args.task_prefix),
        "merge_target_branch": str(args.merge_target_branch),
        "merge_target_tip": _git_branch_tip(repo_root, str(args.merge_target_branch)),
        "board_status_counts": dict(board_counts),
        "shards": shards,
        "merge_queue": merge_queue,
        "notes": [
            "Board Status:completed is durable board text; merge-queued is daemon projection.",
            "Completion lands only after merge into merge_target_branch.",
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LIG multi-lane + merge-train operator status"
    )
    default_repo = _repo_root_from_script()
    parser.add_argument(
        "--repo-root",
        default=str(default_repo),
        help="ipfs_datasets_py repository root",
    )
    parser.add_argument(
        "--state-root",
        default="data/agent_supervisor/logic_intent_legal_gate",
        help="relative or absolute multi-lane state root",
    )
    parser.add_argument(
        "--todo-path",
        default="docs/architecture/logic_intent_legal_gate.todo.md",
        help="relative or absolute LIG task board",
    )
    parser.add_argument("--task-prefix", default="LIG-")
    parser.add_argument("--shard-count", type=int, default=4)
    parser.add_argument(
        "--merge-target-branch",
        default=os.environ.get(
            "MERGE_TARGET_BRANCH", "feature/logic-intent-legal-gate"
        ),
    )
    parser.add_argument(
        "--merge-queue-dir",
        default=os.environ.get("MERGE_QUEUE_DIR") or "",
        help="optional explicit shared merge queue directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if not args.merge_queue_dir:
        args.merge_queue_dir = None
    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
