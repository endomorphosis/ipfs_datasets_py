#!/usr/bin/env python3
"""Source-checkout entry with refill policy mapping for configured boards."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_accelerate_py.agent_supervisor.runtime import configured_board_scheduler as _scheduler  # noqa: E402


_upstream_common_args = _scheduler.configured_board_common_args


def _configured_board_common_args(board, *, implement):
    """Map the bounded refill fields omitted by the pinned generic adapter."""

    args = list(_upstream_common_args(board, implement=implement))
    policy = board.payload.get("refill_policy", {})

    for enabled_key, negative_flag in (
        ("objective_task_janitor_enabled", "--no-objective-task-janitor"),
        (
            "objective_goal_completion_reconcile_enabled",
            "--no-objective-goal-completion-reconcile",
        ),
        ("objective_goal_migration_enabled", "--no-objective-goal-migration"),
    ):
        if policy.get(enabled_key) is True and negative_flag in args:
            args.remove(negative_flag)

    mappings = (
        ("--objective-scan-min-open-tasks", "minimum_open_tasks"),
        ("--objective-scan-max-findings", "maximum_findings_per_scan"),
        ("--objective-scan-cooldown-seconds", "cooldown_seconds"),
        ("--objective-refill-timeout-seconds", "scan_timeout_seconds"),
        ("--codebase-scan-min-open-tasks", "minimum_open_tasks"),
        ("--codebase-scan-max-findings", "maximum_findings_per_scan"),
        ("--codebase-scan-cooldown-seconds", "cooldown_seconds"),
        ("--codebase-refill-timeout-seconds", "scan_timeout_seconds"),
    )
    for flag, key in mappings:
        value = policy.get(key)
        if value is not None:
            args.extend((flag, str(value)))
    return tuple(args)


_scheduler.configured_board_common_args = _configured_board_common_args
main = _scheduler.main


if __name__ == "__main__":
    raise SystemExit(main())
