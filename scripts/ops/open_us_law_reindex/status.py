#!/usr/bin/env python3
"""Report two-sample liveness and stall health for the Open US Law supervisor."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = Path("config/agent_supervisor_open_us_law_reindex_scheduler.json")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ops.legal_corpora_reindex.status import _observation, sample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--observe-seconds", type=float, default=0.0)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    try:
        report = sample(root, config.resolve())
        report["schema"] = "ipfs_datasets_py/open-us-law-reindex-status@1"
        if args.observe_seconds > 0:
            seconds = min(max(args.observe_seconds, 0.0), 60.0)
            first = report
            time.sleep(seconds)
            report = sample(root, config.resolve())
            report["schema"] = "ipfs_datasets_py/open-us-law-reindex-status@1"
            report["observation"] = _observation(first, report, seconds)
            if report["overall_health"] in {"healthy", "starting"}:
                stalled = [
                    lane["index"] for lane in report["observation"]["lanes"]
                    if lane["after_health"] == "healthy"
                    and not lane["heartbeat_advanced"]
                    and not lane["durable_progress_changed"]
                ]
                if stalled:
                    report["overall_health"] = "unhealthy"
                    report["observation_errors"] = [
                        f"no heartbeat or durable progress across observation for lanes {stalled}"
                    ]
    except Exception as exc:
        report = {
            "schema": "ipfs_datasets_py/open-us-law-reindex-status@1",
            "overall_health": "malformed",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(report["overall_health"])
        master = report.get("master", {})
        print(f"master pid={master.get('pid')} alive={master.get('alive')}")
        for lane in report.get("lanes", []):
            tasks = lane["tasks"]
            print(
                f"lane {lane['index']}: {lane['health']} "
                f"active={tasks['active_task_id'] or '-'} "
                f"completed={tasks['completed_count']} ready={tasks['ready_count']} "
                f"waiting={tasks['waiting_count']} blocked={tasks['blocked_count']}"
            )
    health = report.get("overall_health")
    if health in {"healthy", "starting", "completed"}:
        return 0
    if health == "malformed":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
