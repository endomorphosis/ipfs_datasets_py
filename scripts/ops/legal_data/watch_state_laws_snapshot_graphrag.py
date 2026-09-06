#!/usr/bin/env python3
"""Watch the 51-jurisdiction snapshot GraphRAG build and resume it if it dies.

Quiet BM25 sorts are not stalls: counters in parquet/sort checkpoints must stop
moving. Official live 51-state seals and Hub current-bundle publishes are
host-blocked on this R&D machine and are never auto-retried.

Monitor mode prints only DONE/FAILED/CANCELLED.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

HERE = Path(__file__).resolve()
WORKTREE = HERE.parents[3]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from ipfs_datasets_py.processors.legal_data.state_laws_snapshot_graphrag import (  # noqa: E402
    DEFAULT_SNAPSHOT_HUB_REPO_ID,
    publish_snapshot_research_hf,
)
from ipfs_datasets_py.processors.legal_data.state_laws_snapshot_progress import (  # noqa: E402
    DEFAULT_DEST,
    DEFAULT_STATUS_PATH,
    classify_progress,
    load_status,
    snapshot_graphrag_progress,
    write_status,
)

BUILDER = (
    WORKTREE
    / "scripts"
    / "ops"
    / "legal_data"
    / "build_state_laws_snapshot_sparse_graphrag.py"
)
CORPUS = (
    Path.home()
    / ".ipfs_datasets"
    / "state_laws"
    / "snapshot-graphrag-corpus-v2026.08.31-all51"
)
PYTHON = Path.home() / ".local" / "bin" / "python"


def _resume_builder(dest: Path) -> int:
    log = dest / "build.watch-resume.log"
    dest.mkdir(parents=True, exist_ok=True)
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o664)
    try:
        proc = subprocess.Popen(
            [
                str(PYTHON if PYTHON.is_file() else sys.executable),
                "-u",
                str(BUILDER),
                "--corpus-root",
                str(CORPUS),
                "--output-dir",
                str(dest),
                "--prefer-real-embeddings",
                "--print-json",
            ],
            cwd=str(WORKTREE),
            stdout=fd,
            stderr=fd,
            start_new_session=True,
            close_fds=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    finally:
        os.close(fd)
    return int(proc.pid)


def _emit(kind: str, *, monitor: bool) -> None:
    if monitor:
        print(kind, flush=True)


def run_once(
    *,
    dest: Path,
    status_path: Path,
    auto_resume: bool,
    auto_publish: bool,
    monitor: bool,
    stall_seconds: float,
    hub_repo_id: str,
) -> dict:
    current = snapshot_graphrag_progress(dest)
    previous = load_status(status_path)
    verdict = classify_progress(
        current, previous=previous, stall_seconds=stall_seconds
    )
    current["health"] = verdict["health"]
    current["health_reason"] = verdict["reason"]
    current["auto_resume"] = False
    previous_health = str((previous or {}).get("health") or "")
    if (
        auto_resume
        and verdict.get("retry")
        and verdict["health"] == "blocked"
        and not current.get("process_alive")
    ):
        pid = _resume_builder(dest)
        current["auto_resume"] = True
        current["resumed_pid"] = pid
        current["health"] = "progressing"
        current["health_reason"] = f"auto_resumed_pid={pid}"
        if previous_health != "progressing":
            _emit("FAILED", monitor=monitor)
    elif verdict["health"] == "complete":
        already = str((previous or {}).get("hub_publish_status") or "")
        if auto_publish and already != "uploaded":
            try:
                published = publish_snapshot_research_hf(
                    dest / "hf-release",
                    repo_id=hub_repo_id,
                    dry_run=False,
                )
                current["hub_publish"] = published
                current["hub_publish_status"] = published.get("status")
            except Exception as exc:
                current["hub_publish_status"] = "error"
                current["hub_publish_error"] = f"{type(exc).__name__}:{exc}"
                if previous_health != "complete":
                    _emit("FAILED", monitor=monitor)
        if previous_health != "complete" and current.get("hub_publish_status") != "error":
            _emit("DONE", monitor=monitor)
    elif verdict["health"] in {"stalled", "blocked"}:
        if previous_health not in {"stalled", "blocked"}:
            _emit("FAILED", monitor=monitor)
    write_status(status_path, current)
    return current


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--status-path", type=Path, default=DEFAULT_STATUS_PATH)
    parser.add_argument("--interval-seconds", type=float, default=300.0)
    parser.add_argument("--stall-seconds", type=float, default=20 * 60)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--auto-resume", action="store_true")
    parser.add_argument(
        "--auto-publish",
        action="store_true",
        help="Upload the snapshot/research GraphRAG to Hub when complete. Never current-bundle.",
    )
    parser.add_argument(
        "--hub-repo-id",
        default=DEFAULT_SNAPSHOT_HUB_REPO_ID,
        help="Research dataset repo (default Publicus/state-laws-snapshot-graphrag).",
    )
    parser.add_argument(
        "--monitor-events",
        action="store_true",
        help="Print only DONE/FAILED/CANCELLED for a session monitor.",
    )
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        while True:
            snapshot = run_once(
                dest=args.dest.expanduser().resolve(),
                status_path=args.status_path.expanduser().resolve(),
                auto_resume=bool(args.auto_resume),
                auto_publish=bool(args.auto_publish),
                monitor=bool(args.monitor_events),
                stall_seconds=float(args.stall_seconds),
                hub_repo_id=str(args.hub_repo_id),
            )
            if args.print_json and not args.monitor_events:
                print(json.dumps(snapshot, indent=2, sort_keys=True, default=str))
            if not args.loop:
                return 0
            if snapshot.get("health") == "complete":
                return 0
            time.sleep(max(5.0, float(args.interval_seconds)))
    except KeyboardInterrupt:
        if args.monitor_events:
            print("CANCELLED", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
