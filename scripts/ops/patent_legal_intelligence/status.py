#!/usr/bin/env python3
"""Content-free health report for the patent-legal implementation supervisors."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_state_root() -> Path:
    state_base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state_base / "ipfs_accelerate_py" / "patent-legal-intelligence-v1"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _read_pid(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip().split()[0]
        pid = int(value)
    except (OSError, IndexError, ValueError):
        return None
    return pid if pid > 0 else None


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _cmdline(pid: int | None) -> str:
    if not pid:
        return ""
    try:
        raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, *, fallback_path: Path | None = None) -> float | None:
    parsed = _parse_time(value)
    if parsed is not None:
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
    if fallback_path and fallback_path.exists():
        try:
            return max(0.0, datetime.now(timezone.utc).timestamp() - fallback_path.stat().st_mtime)
        except OSError:
            return None
    return None


def _int_first(payloads: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> int:
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def _list_first(payloads: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> list[Any]:
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return list(value)
    return []


def _string_first(payloads: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> str:
    for payload in payloads:
        for key in keys:
            value = str(payload.get(key) or "").strip()
            if value:
                return value
    return ""


def _git_tip(repo_root: Path, branch: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", branch],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _queue_summary(queue_dir: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    task_ids: set[str] = set()
    malformed = 0
    if not queue_dir.is_dir():
        return {"exists": False, "path": str(queue_dir), "counts": {}, "task_ids": []}
    for path in sorted(queue_dir.rglob("*.json"))[:500]:
        payload = _load_json(path)
        if payload is None:
            malformed += 1
            continue
        status = str(payload.get("status") or payload.get("state") or "").strip().lower()
        if status:
            counts[status] = counts.get(status, 0) + 1
        task_id = str(
            payload.get("canonical_task_id")
            or payload.get("task_id")
            or payload.get("source_task_id")
            or ""
        ).strip()
        if task_id.startswith("PATLAW-"):
            task_ids.add(task_id)
    return {
        "exists": True,
        "path": str(queue_dir),
        "counts": dict(sorted(counts.items())),
        "task_ids": sorted(task_ids),
        "malformed_json": malformed,
    }


def _shard_health(
    *,
    shard: int,
    state_root: Path,
    heartbeat_limit: int,
    log_limit: int,
    ready_grace: int,
    startup_grace: int,
) -> dict[str, Any]:
    shard_root = state_root / "shards" / str(shard)
    state_dir = shard_root / "state"
    prefix = f"patlaw_shard_{shard}"
    outer_pid_path = shard_root / "supervisor.pid"
    managed_pid_path = state_dir / f"{prefix}_managed_daemon.pid"
    status_path = state_dir / f"{prefix}_supervisor_status.json"
    task_path = state_dir / f"{prefix}_task_state.json"
    incident_path = state_dir / "implementation-protected-path-incident.json"
    outer_log = shard_root / "logs" / "supervisor.log"

    outer_pid = _read_pid(outer_pid_path)
    managed_pid = _read_pid(managed_pid_path)
    outer_alive = _pid_alive(outer_pid)
    managed_alive = _pid_alive(managed_pid)
    outer_cmdline = _cmdline(outer_pid)
    managed_cmdline = _cmdline(managed_pid)
    status = _load_json(status_path) or {}
    task = _load_json(task_path) or {}
    payloads = (task, status)

    active_task = _string_first(payloads, ("active_task_id", "last_implementation_task_id"))
    active_phase = _string_first(payloads, ("active_phase", "phase"))
    active_log_text = _string_first(payloads, ("active_log_path", "implementation_log_path"))
    active_log = Path(active_log_text) if active_log_text else None
    if active_log is not None and not active_log.is_absolute():
        active_log = state_dir / active_log
    worker_pids: list[int] = []
    for value in _list_first(payloads, ("active_worker_pids", "worker_pids")):
        try:
            pid = int(value)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            worker_pids.append(pid)
    worker_alive = [pid for pid in worker_pids if _pid_alive(pid)]
    worker_count = max(
        len(worker_pids),
        _int_first(payloads, ("active_worker_count", "worker_count")),
    )
    ready_count = _int_first(
        payloads,
        ("eligible_ready_count", "selectable_ready_count", "ready_count"),
    )
    waiting_count = _int_first(payloads, ("waiting_count",))
    blocked_count = _int_first(payloads, ("blocked_count",))
    completed_count = _int_first(payloads, ("completed_count",))
    idle_reason = _string_first(payloads, ("selection_idle_reason", "idle_reason"))
    supervisor_state = _string_first((status,), ("status", "state")) or "unknown"
    restart_count = _int_first((status,), ("restart_count", "restarts"))
    last_recycle_reason = _string_first((status,), ("last_recycle_reason",))

    heartbeat_value = _string_first(
        payloads,
        ("updated_at", "heartbeat_at", "last_progress_at", "observed_at"),
    )
    heartbeat_age = _age_seconds(heartbeat_value, fallback_path=status_path if status else task_path)
    pid_age = _age_seconds("", fallback_path=outer_pid_path)
    progress_age = _age_seconds(
        _string_first(payloads, ("last_progress_at", "heartbeat_at", "updated_at")),
        fallback_path=task_path if task else status_path,
    )
    selected_log = active_log if active_log and active_log.exists() else outer_log
    log_age = _age_seconds("", fallback_path=selected_log)

    reasons: list[str] = []
    notes: list[str] = []
    starting = bool(outer_alive and pid_age is not None and pid_age <= startup_grace)
    if not outer_alive:
        reasons.append("outer supervisor PID is not alive")
    elif "implementation_supervisor" not in outer_cmdline:
        reasons.append("outer PID command does not match implementation_supervisor")
    if outer_alive and not managed_alive and not starting:
        reasons.append("managed daemon PID is not alive after startup grace")
    if managed_alive and (prefix not in managed_cmdline or "implementation_daemon" not in managed_cmdline):
        reasons.append("managed PID command does not match this shard")
    if not status and not starting:
        reasons.append("supervisor status is missing after startup grace")
    if heartbeat_age is not None and heartbeat_age > heartbeat_limit and not starting:
        reasons.append(f"heartbeat is stale ({heartbeat_age:.0f}s > {heartbeat_limit}s)")
    if status.get("stalled_without_active_worker") is True:
        reasons.append("supervisor reports stalled_without_active_worker")
    if incident_path.exists():
        reasons.append("protected-path incident is latched")
    if blocked_count > 0:
        reasons.append(f"task projection has {blocked_count} blocked task(s)")
    if worker_count > 0 and not worker_alive and active_task and not starting:
        reasons.append("active task declares workers but no worker PID is alive")
    if active_task and log_age is not None and log_age > log_limit and not starting:
        reasons.append(f"active implementation log is stale ({log_age:.0f}s > {log_limit}s)")
    if (
        ready_count > 0
        and not active_task
        and not worker_alive
        and progress_age is not None
        and progress_age > ready_grace
        and not starting
    ):
        reasons.append(
            f"{ready_count} task(s) ready without active work for {progress_age:.0f}s"
        )
    if idle_reason == "provider_capacity_backoff":
        notes.append("provider capacity backoff is active; verify bounded retry time")
    if idle_reason == "all_selectable_ready_tasks_reached_max_task_attempts":
        reasons.append("all selectable ready tasks reached the attempt limit")
    if idle_reason == "no_shard_selectable_ready_tasks" and ready_count > 0:
        reasons.append("ready work exists but the reviewed execution slice cannot select it")
    if last_recycle_reason:
        notes.append(f"last recycle: {last_recycle_reason}")

    health = "unhealthy" if reasons else ("starting" if starting and not managed_alive else "healthy")
    return {
        "shard": shard,
        "health": health,
        "reasons": reasons,
        "notes": notes,
        "outer_pid": outer_pid,
        "outer_alive": outer_alive,
        "managed_pid": managed_pid,
        "managed_alive": managed_alive,
        "supervisor_state": supervisor_state,
        "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "active_task_id": active_task,
        "active_phase": active_phase,
        "active_worker_pids": worker_pids,
        "active_worker_pids_alive": worker_alive,
        "active_log_path": str(active_log) if active_log else "",
        "active_log_age_seconds": round(log_age, 1) if log_age is not None else None,
        "ready_count": ready_count,
        "waiting_count": waiting_count,
        "blocked_count": blocked_count,
        "completed_count": completed_count,
        "selection_idle_reason": idle_reason,
        "restart_count": restart_count,
        "status_path": str(status_path),
        "task_state_path": str(task_path),
        "protected_path_incident": str(incident_path) if incident_path.exists() else "",
    }


def build_report(repo_root: Path, state_root: Path, config_path: Path) -> dict[str, Any]:
    config = _load_json(config_path) or {}
    health = config.get("health") if isinstance(config.get("health"), Mapping) else {}
    supervisor = config.get("supervisor") if isinstance(config.get("supervisor"), Mapping) else {}
    shard_count = int(config.get("shard_count") or 4)
    shards = [
        _shard_health(
            shard=shard,
            state_root=state_root,
            heartbeat_limit=int(health.get("maximum_heartbeat_age_seconds") or 120),
            log_limit=int(health.get("maximum_active_log_age_seconds") or 600),
            ready_grace=int(health.get("ready_without_worker_grace_seconds") or 120),
            startup_grace=int(supervisor.get("startup_grace_seconds") or 300),
        )
        for shard in range(shard_count)
    ]
    overall = "unhealthy" if any(row["health"] == "unhealthy" for row in shards) else (
        "starting" if any(row["health"] == "starting" for row in shards) else "healthy"
    )
    branch = str(config.get("merge_target_branch") or "feature/patent-legal-intelligence")
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "overall_health": overall,
        "repo_root": str(repo_root),
        "state_root": str(state_root),
        "merge_target_branch": branch,
        "merge_target_tip": _git_tip(repo_root, branch),
        "provider": config.get("provider") or {},
        "shards": shards,
        "merge_queue": _queue_summary(state_root / "merge_queue"),
    }


def _print_human(report: Mapping[str, Any]) -> None:
    print(
        f"PATLAW supervisor health: {str(report.get('overall_health')).upper()} "
        f"@ {report.get('as_of')}"
    )
    print(
        f"target={report.get('merge_target_branch')} tip={report.get('merge_target_tip') or '(missing)'} "
        f"state={report.get('state_root')}"
    )
    for row in report.get("shards", []):
        print(
            f"shard {row['shard']}: {row['health']} "
            f"outer={row.get('outer_pid') or '-'}[{('up' if row.get('outer_alive') else 'down')}] "
            f"daemon={row.get('managed_pid') or '-'}[{('up' if row.get('managed_alive') else 'down')}] "
            f"task={row.get('active_task_id') or '-'} phase={row.get('active_phase') or '-'} "
            f"ready={row.get('ready_count')} waiting={row.get('waiting_count')} "
            f"blocked={row.get('blocked_count')} completed={row.get('completed_count')} "
            f"heartbeat_age={row.get('heartbeat_age_seconds') if row.get('heartbeat_age_seconds') is not None else '-'}s"
        )
        for reason in row.get("reasons", []):
            print(f"  ERROR: {reason}")
        for note in row.get("notes", []):
            print(f"  note: {note}")
    queue = report.get("merge_queue") or {}
    print(
        f"merge queue: exists={queue.get('exists')} counts={queue.get('counts') or {}} "
        f"tasks={len(queue.get('task_ids') or [])} path={queue.get('path')}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    parser.add_argument("--state-root", type=Path, default=_default_state_root())
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/agent_supervisor_patent_legal_intelligence.json"),
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    state_root = Path(os.environ.get("PATLAW_STATE_ROOT") or args.state_root).expanduser().resolve()
    config_path = args.config.expanduser()
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    report = build_report(repo_root, state_root, config_path.resolve())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 1 if report["overall_health"] == "unhealthy" else 0


if __name__ == "__main__":
    raise SystemExit(main())
