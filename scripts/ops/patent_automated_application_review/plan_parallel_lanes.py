#!/usr/bin/env python3
"""Plan PAAR multi-lane slices via ipfs_accelerate_py analysis-driven planner.

Uses predicted_files/outputs + optional Python AST enrichment and the core
conflict graph to maximize concurrent shards without co-scheduling conflicting
edits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_accelerator(repo_root: Path, requested: str) -> Path:
    candidates = []
    if requested:
        candidates.append(Path(requested))
    env = os.environ.get("PAAR_ACCELERATE_ROOT") or os.environ.get(
        "PATLAW_ACCELERATE_ROOT"
    )
    if env:
        candidates.append(Path(env))
    candidates.append(repo_root.parent / "ipfs_accelerate_py")
    for cand in candidates:
        resolved = cand.expanduser().resolve()
        if (resolved / "ipfs_accelerate_py" / "agent_supervisor").is_dir():
            return resolved
    raise SystemExit("compatible ipfs_accelerate_py worktree not found")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    parser.add_argument("--accelerate-root", default="")
    parser.add_argument(
        "--todo-path",
        default="docs/architecture/patent_automated_application_review.todo.md",
    )
    parser.add_argument(
        "--config-path",
        default="config/agent_supervisor_patent_automated_application_review.json",
    )
    parser.add_argument("--max-lanes", type=int, default=6)
    parser.add_argument("--no-ast", action="store_true")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write optimized lane_slices into the PAAR scheduler config",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo_root.expanduser().resolve()
    accel = _resolve_accelerator(repo, args.accelerate_root)
    sys.path.insert(0, str(accel))
    sys.path.insert(0, str(repo))

    from ipfs_accelerate_py.agent_supervisor.planning.parallel_lane_planner import (
        apply_lane_slices_to_config,
        plan_parallel_lanes_from_todo_path,
    )

    todo = (repo / args.todo_path).resolve()
    config = (repo / args.config_path).resolve()
    plan = plan_parallel_lanes_from_todo_path(
        todo,
        max_lanes=int(args.max_lanes),
        repo_root=repo,
        use_ast=not bool(args.no_ast),
    )
    if args.write:
        apply_lane_slices_to_config(config, plan, write=True)
        print(f"updated lane_slices in {config}", file=sys.stderr)

    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    else:
        print(
            f"PAAR parallel plan: tasks={plan.task_count} lanes={plan.max_lanes} "
            f"width={plan.independent_width} blocking={plan.blocking_edge_count}"
        )
        for lane, ids in sorted(
            plan.lane_slices.items(),
            key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0,
        ):
            print(f"  shard {lane} ({len(ids)}): {', '.join(ids) or '(empty)'}")
        for line in plan.rationale:
            print(f"  # {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
