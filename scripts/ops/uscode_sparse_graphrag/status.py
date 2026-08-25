#!/usr/bin/env python3
"""Inspect ownership, heartbeat, progress, and stall health for the US Code board."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CONFIG = Path("config/agent_supervisor_uscode_sparse_graphrag_scheduler.json")
FATAL_STATUS = {"launch_failed", "max_restarts_reached", "child_exited", "termination_blocked"}


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _read_pid(path: Path) -> int | None:
    try:
        pid = int(path.read_text(encoding="utf-8").strip().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if pid > 0 else None


def _proc_argv(pid: int | None) -> list[str]:
    if not pid:
        return []
    try:
        raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [item.decode("utf-8", "replace") for item in raw.split(b"\0") if item]


def _proc_ppid(pid: int | None) -> int | None:
    if not pid:
        return None
    try:
        return int((Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8").split()[3])
    except (OSError, ValueError, IndexError):
        return None


def _alive(pid: int | None) -> bool:
    return bool(pid and (Path("/proc") / str(pid)).is_dir())


def _arg_value(argv: list[str], key: str) -> str:
    try:
        index = argv.index(key)
    except ValueError:
        return ""
    return argv[index + 1] if index + 1 < len(argv) else ""


def _parse_time(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
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
    return parsed.timestamp()


def _age(value: Any = None, path: Path | None = None) -> float | None:
    stamp = _parse_time(value)
    if stamp is None and path is not None:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return None
    return max(0.0, time.time() - stamp) if stamp is not None else None


def _int(payload: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        try:
            if payload.get(key) is not None:
                return int(payload[key])
        except (TypeError, ValueError):
            pass
    return 0


def _string(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _pid_descends_from(pid: int, ancestor: int) -> bool:
    seen: set[int] = set()
    current: int | None = pid
    while current and current > 1 and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        current = _proc_ppid(current)
    return False


def _all_processes() -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return processes
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        pid = int(item.name)
        argv = _proc_argv(pid)
        if argv:
            processes.append({"pid": pid, "ppid": _proc_ppid(pid), "argv": argv})
    return processes


def _progress_signature(task: Mapping[str, Any]) -> str:
    fields = {
        "active_task_id": task.get("active_task_id"),
        "active_task_cid": task.get("active_task_cid"),
        "active_attempt": task.get("active_attempt"),
        "active_phase": task.get("active_phase"),
        "implementation_in_progress": task.get("implementation_in_progress"),
        "completed_task_ids": sorted(task.get("completed_task_ids") or []),
        "task_statuses": task.get("task_statuses") or {},
        "implementation_attempts_by_cid": task.get("implementation_attempts_by_cid") or {},
        "last_implementation_finished_at": task.get("last_implementation_finished_at"),
        "last_implementation_returncode": task.get("last_implementation_returncode"),
        "last_implementation_commit": task.get("last_implementation_commit"),
        "last_merge_finished_at": task.get("last_merge_finished_at"),
        "last_merge_returncode": task.get("last_merge_returncode"),
        "last_merge_commit": task.get("last_merge_commit"),
        "selection_idle_reason": task.get("selection_idle_reason"),
    }
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _queue_summary(path: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    malformed = 0
    for item in sorted(path.rglob("*.json"))[:1000] if path.is_dir() else []:
        payload = _load_json(item)
        if payload is None:
            malformed += 1
            continue
        state = _string(payload, "status", "state") or "unknown"
        counts[state] = counts.get(state, 0) + 1
    return {"path": str(path), "exists": path.is_dir(), "counts": counts, "malformed": malformed}


def _git_tip(repo_root: Path, branch: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", branch],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _lane_sample(
    *,
    index: int,
    repo_root: Path,
    state_root: Path,
    todo_path: Path,
    entry_path: Path,
    merge_queue: Path,
    config: Mapping[str, Any],
    master_pid: int | None,
    master_age: float | None,
    processes: list[dict[str, Any]],
) -> dict[str, Any]:
    lane_dir = state_root / f"lane-{index}"
    prefix = f"uscir_lane_{index}"
    outer_pid_path = lane_dir / f"{prefix}_supervisor.pid"
    daemon_pid_path = lane_dir / f"{prefix}_managed_daemon.pid"
    identity_path = lane_dir / f"{prefix}_managed_daemon.identity.json"
    status_path = lane_dir / f"{prefix}_supervisor_status.json"
    task_path = lane_dir / f"{prefix}_task_state.json"
    incident_path = lane_dir / "implementation-protected-path-incident.json"

    outer_pid = _read_pid(outer_pid_path)
    daemon_pid = _read_pid(daemon_pid_path)
    outer_argv = _proc_argv(outer_pid)
    daemon_argv = _proc_argv(daemon_pid)
    status = _load_json(status_path) or {}
    task = _load_json(task_path) or {}
    identity = _load_json(identity_path) or {}
    reasons: list[str] = []
    notes: list[str] = []
    startup_grace = float(config["watchdog_startup_grace_seconds"])
    starting = bool(master_pid and _alive(master_pid) and master_age is not None and master_age <= startup_grace)

    expected_outer = [
        proc for proc in processes
        if str(entry_path) in proc["argv"]
        and _arg_value(proc["argv"], "--state-dir") == str(lane_dir)
        and _arg_value(proc["argv"], "--state-prefix") == prefix
    ]
    expected_daemons = [
        proc for proc in processes
        if "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon" in proc["argv"]
        and _arg_value(proc["argv"], "--state-dir") == str(lane_dir)
        and _arg_value(proc["argv"], "--state-prefix") == prefix
    ]
    if len(expected_outer) > 1:
        reasons.append(f"duplicate outer supervisors: {[item['pid'] for item in expected_outer]}")
    if len(expected_daemons) > 1:
        reasons.append(f"duplicate managed daemons: {[item['pid'] for item in expected_daemons]}")
    if not _alive(outer_pid) and not starting:
        reasons.append("outer supervisor PID is missing or dead")
    if not _alive(daemon_pid) and not starting:
        reasons.append("managed daemon PID is missing or dead")
    if _alive(outer_pid):
        if str(entry_path) not in outer_argv:
            reasons.append("outer PID command does not name the sealed implementation entry")
        for key, expected in (
            ("--todo-path", str(todo_path)),
            ("--state-dir", str(lane_dir)),
            ("--state-prefix", prefix),
            ("--task-shard-count", "4"),
            ("--task-shard-index", str(index)),
            ("--merge-queue-dir", str(merge_queue)),
        ):
            if _arg_value(outer_argv, key) != expected:
                reasons.append(f"outer command mismatch for {key}")
        for flag in ("--strict-task-sharding", "--implement"):
            if flag not in outer_argv:
                reasons.append(f"outer command missing {flag}")
        if master_pid and not _pid_descends_from(outer_pid or 0, master_pid):
            reasons.append("outer supervisor is orphaned from the configured master")
    if _alive(daemon_pid):
        if "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon" not in daemon_argv:
            reasons.append("managed PID is not the implementation daemon module")
        for key, expected in (
            ("--todo-path", str(todo_path)),
            ("--state-dir", str(lane_dir)),
            ("--state-prefix", prefix),
            ("--task-shard-count", "4"),
            ("--task-shard-index", str(index)),
        ):
            if _arg_value(daemon_argv, key) != expected:
                reasons.append(f"managed command mismatch for {key}")
        if outer_pid and not _pid_descends_from(daemon_pid or 0, outer_pid) and master_pid and not _pid_descends_from(daemon_pid or 0, master_pid):
            reasons.append("managed daemon is orphaned from the lane process tree")

    identity_pid = _int(identity, "pid", "child_pid")
    if identity and identity_pid and daemon_pid and identity_pid != daemon_pid:
        reasons.append("managed daemon identity PID does not match marker")
    if status and _int(status, "supervisor_pid") not in {0, outer_pid}:
        reasons.append("status supervisor PID does not match marker")
    if status and _int(status, "daemon_pid") not in {0, daemon_pid}:
        reasons.append("status daemon PID does not match marker")

    heartbeat = _string(status, "updated_at", "heartbeat_at")
    heartbeat_age = _age(heartbeat, status_path if status else None)
    heartbeat_limit = min(
        float(config["stale_seconds"]),
        max(3 * float(config["check_interval_seconds"]), 120.0),
    )
    if not status and not starting:
        reasons.append("supervisor status is missing")
    elif heartbeat_age is None and not starting:
        reasons.append("supervisor heartbeat is missing or malformed")
    elif heartbeat_age is not None and heartbeat_age > heartbeat_limit and not starting:
        reasons.append(f"supervisor heartbeat is stale ({heartbeat_age:.1f}s > {heartbeat_limit:.1f}s)")

    supervisor_state = _string(status, "status", "state") or ("starting" if starting else "unknown")
    if supervisor_state in FATAL_STATUS:
        reasons.append(f"fatal supervisor state: {supervisor_state}")
    if status.get("stalled_without_active_worker") is True:
        reasons.append("supervisor reports stalled_without_active_worker")
    if incident_path.exists():
        reasons.append("protected-path incident is latched")
    if _string(status, "active_agentic_maintenance_error", "maintenance_error"):
        reasons.append("agentic maintenance reports an error")

    completed = _int(task, "completed_count")
    ready = _int(task, "eligible_ready_count", "selectable_ready_count", "ready_count")
    waiting = _int(task, "waiting_count")
    blocked = _int(task, "blocked_count")
    external = _int(task, "external_reserved_count")
    task_count = _int(task, "task_count")
    active_task = _string(task, "active_task_id")
    active_phase = _string(task, "active_phase")
    implementation_in_progress = task.get("implementation_in_progress") is True
    active_worktree = _string(
        task,
        "active_worktree_path",
        "last_implementation_worktree_path",
    )
    if blocked:
        reasons.append(f"{blocked} blocked task(s)")
    worker_pids: list[int] = []
    for value in task.get("active_worker_pids") or status.get("active_worker_pids") or []:
        try:
            worker_pids.append(int(value))
        except (TypeError, ValueError):
            pass
    provider_workers = [
        process["pid"]
        for process in processes
        if active_worktree
        and _arg_value(process["argv"], "--cwd") == active_worktree
        and any("grok" in Path(token).name or "codex" in Path(token).name for token in process["argv"][:2])
    ]
    live_workers = sorted({
        *[pid for pid in worker_pids if _alive(pid)],
        *[pid for pid in provider_workers if _alive(pid)],
    })
    declared_workers = max(
        len(worker_pids),
        len(provider_workers),
        _int(task, "active_worker_count"),
        _int(status, "active_worker_count"),
    )
    if declared_workers and not live_workers and active_task and not starting:
        reasons.append("active task declares workers but no worker PID is alive")

    active_started = _string(task, "active_task_started_at", "active_phase_started_at")
    active_age = _age(active_started)
    if active_age is not None and active_age > float(config["implementation_max_timeout_seconds"]):
        reasons.append("active task exceeds implementation hard timeout")
    active_log_text = _string(task, "active_log_path")
    active_log = Path(active_log_text) if active_log_text else None
    if active_log is not None and not active_log.is_absolute():
        active_log = lane_dir / active_log
    active_log_age = _age(path=active_log) if active_log else None
    if (
        implementation_in_progress
        and active_log_age is not None
        and active_log_age > float(config["implementation_log_stall_seconds"])
        and not live_workers
    ):
        reasons.append("active implementation log is stale without a recognized live worker")

    progress_age = _age(_string(task, "last_progress_at", "heartbeat_at"), task_path if task else None)
    idle_grace = max(2 * float(config["daemon_interval_seconds"]), 3 * float(config["check_interval_seconds"]))
    idle_reason = _string(task, "selection_idle_reason", "idle_reason")
    if ready > 0 and not active_task and not implementation_in_progress and not live_workers and not starting:
        if progress_age is None or progress_age > idle_grace:
            reasons.append(f"{ready} eligible task(s) ready without active work past grace")
    if idle_reason == "provider_capacity_backoff":
        retry_at = _parse_time(task.get("retry_at") or status.get("retry_at"))
        if retry_at is None or retry_at <= time.time():
            reasons.append("provider capacity backoff is missing or expired")
        else:
            notes.append("typed provider capacity backoff is active")

    last_merge_returncode = task.get("last_merge_returncode")
    if last_merge_returncode not in (None, 0, "0") and task.get("last_merge_commit") in (None, ""):
        reasons.append("latest merge failed without a reconciled merge commit")
    for path_key in ("current_status_path", "progress_path"):
        raw = _string(status, path_key)
        if raw:
            target = Path(raw)
            if not target.is_absolute():
                target = lane_dir / target
            try:
                target.resolve().relative_to(lane_dir.resolve())
            except ValueError:
                reasons.append(f"status {path_key} escapes its lane directory")

    if starting and not reasons:
        health = "starting"
    else:
        health = "healthy" if not reasons else "unhealthy"
    return {
        "index": index,
        "health": health,
        "reasons": reasons,
        "notes": notes,
        "paths": {
            "state_dir": str(lane_dir),
            "status": str(status_path),
            "task_state": str(task_path),
            "identity": str(identity_path),
            "incident": str(incident_path),
        },
        "outer": {"pid": outer_pid, "alive": _alive(outer_pid), "ppid": _proc_ppid(outer_pid), "argv": outer_argv, "matches": [item["pid"] for item in expected_outer]},
        "daemon": {"pid": daemon_pid, "alive": _alive(daemon_pid), "ppid": _proc_ppid(daemon_pid), "argv": daemon_argv, "identity_pid": identity_pid, "matches": [item["pid"] for item in expected_daemons]},
        "supervisor": {
            "state": supervisor_state,
            "updated_at": heartbeat,
            "heartbeat_age_seconds": heartbeat_age,
            "restart_count": _int(status, "restart_count", "restarts"),
            "last_exit_code": status.get("last_exit_code"),
            "last_recycle_reason": status.get("last_recycle_reason"),
            "worker_phase": _string(status, "worker_phase"),
            "stalled_without_active_worker": status.get("stalled_without_active_worker") is True,
        },
        "tasks": {
            "task_count": task_count,
            "completed_count": completed,
            "ready_count": ready,
            "waiting_count": waiting,
            "blocked_count": blocked,
            "external_reserved_count": external,
            "active_task_id": active_task,
            "active_phase": active_phase,
            "active_worktree": active_worktree,
            "active_age_seconds": active_age,
            "implementation_in_progress": implementation_in_progress,
            "selection_idle_reason": idle_reason,
            "last_progress_at": _string(task, "last_progress_at"),
            "progress_age_seconds": progress_age,
            "progress_signature": _progress_signature(task),
        },
        "workers": {"declared": declared_workers, "pids": worker_pids, "provider_pids": provider_workers, "live_pids": live_workers, "active_log": str(active_log) if active_log else "", "active_log_age_seconds": active_log_age},
    }


def sample(repo_root: Path, config_path: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    runtime = config["runtime_paths"]
    state_root = repo_root / runtime["state"]
    logs_root = repo_root / runtime["logs"]
    merge_queue = repo_root / runtime["merge_queue"]
    todo_path = repo_root / config["taskboard_path"]
    entry_path = repo_root / "scripts/ops/agent_supervisor/implementation_supervisor_entry.py"
    master_pid_path = state_root / "configured-board-master.pid"
    master_pid = _read_pid(master_pid_path)
    master_argv = _proc_argv(master_pid)
    master_age = _age(path=master_pid_path)
    master_log_text = _arg_value(master_argv, "--master-log")
    master_log = Path(master_log_text) if master_log_text else None
    master_log_age = _age(path=master_log) if master_log else None
    master_reasons: list[str] = []
    if _alive(master_pid):
        if "ipfs_accelerate_py.agent_supervisor.runtime.multi_supervisor_runner" not in master_argv:
            master_reasons.append("master PID is not the multi-supervisor runner")
        for key, expected in (
            ("--repo-root", str(repo_root)),
            ("--master-pid-path", str(master_pid_path)),
            ("--label", config["board_namespace"]),
            ("--implementation-supervisor-lanes-per-track", str(config["max_lanes"])),
        ):
            if _arg_value(master_argv, key) != expected:
                master_reasons.append(f"master command mismatch for {key}")
        if master_log_age is not None and master_age is not None and master_age > float(config["watchdog_startup_grace_seconds"]):
            if master_log_age > max(3 * float(config["poll_interval_seconds"]), 30.0):
                master_reasons.append("master log is stale")

    processes = _all_processes()
    lanes = [
        _lane_sample(
            index=index,
            repo_root=repo_root,
            state_root=state_root,
            todo_path=todo_path,
            entry_path=entry_path,
            merge_queue=merge_queue,
            config=config,
            master_pid=master_pid,
            master_age=master_age,
            processes=processes,
        )
        for index in range(config["max_lanes"])
    ]

    scoped: list[dict[str, Any]] = []
    runtime_text = str(repo_root / runtime["root"])
    for process in processes:
        joined = "\0".join(process["argv"])
        if config["board_namespace"] in joined or runtime_text in joined:
            scoped.append(process)
    recognized_provider_pids = {
        pid
        for lane in lanes
        for pid in lane["workers"]["provider_pids"]
    }
    unowned = [
        process for process in scoped
        if process["pid"] not in recognized_provider_pids
        and (not master_pid or not _pid_descends_from(process["pid"], master_pid))
    ]
    if master_pid:
        unowned = [process for process in unowned if process["pid"] != master_pid]

    all_completed = bool(
        lanes
        and all(
            lane["tasks"]["task_count"] > 0
            and lane["tasks"]["completed_count"] == lane["tasks"]["task_count"]
            and lane["tasks"]["ready_count"] == 0
            and lane["tasks"]["blocked_count"] == 0
            and not lane["tasks"]["active_task_id"]
            for lane in lanes
        )
    )
    if all_completed and not _alive(master_pid):
        overall = "completed"
    elif not _alive(master_pid):
        overall = "not_started" if not state_root.exists() else "unhealthy"
        master_reasons.append("configured master is not alive and terminal completion is not proven")
    elif master_reasons or unowned or any(lane["health"] == "unhealthy" for lane in lanes):
        overall = "unhealthy"
    elif any(lane["health"] == "starting" for lane in lanes):
        overall = "starting"
    else:
        overall = "healthy"

    return {
        "schema": "ipfs_datasets_py/uscode-sparse-graphrag-status@1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "overall_health": overall,
        "repo_root": str(repo_root),
        "board_namespace": config["board_namespace"],
        "merge_target_branch": config["merge_target_branch"],
        "merge_target_tip": _git_tip(repo_root, config["merge_target_branch"]),
        "master": {
            "pid": master_pid,
            "alive": _alive(master_pid),
            "argv": master_argv,
            "pid_age_seconds": master_age,
            "log": str(master_log) if master_log else "",
            "log_age_seconds": master_log_age,
            "reasons": master_reasons,
        },
        "lanes": lanes,
        "merge_queue": _queue_summary(merge_queue),
        "unowned_processes": scoped if not master_pid else unowned,
    }


def _observation(first: Mapping[str, Any], second: Mapping[str, Any], seconds: float) -> dict[str, Any]:
    lane_observations: list[dict[str, Any]] = []
    for before, after in zip(first.get("lanes", []), second.get("lanes", [])):
        before_time = before["supervisor"]["updated_at"]
        after_time = after["supervisor"]["updated_at"]
        before_sig = before["tasks"]["progress_signature"]
        after_sig = after["tasks"]["progress_signature"]
        lane_observations.append({
            "index": after["index"],
            "heartbeat_advanced": bool(before_time and after_time and before_time != after_time),
            "durable_progress_changed": before_sig != after_sig,
            "before_health": before["health"],
            "after_health": after["health"],
        })
    master_before = first.get("master", {}).get("log_age_seconds")
    master_after = second.get("master", {}).get("log_age_seconds")
    return {
        "seconds": seconds,
        "master_log_advanced": bool(master_before is not None and master_after is not None and master_after < master_before),
        "lanes": lane_observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--observe-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    config_path = args.config if args.config.is_absolute() else repo_root / args.config
    try:
        report = sample(repo_root, config_path.resolve())
        if args.observe_seconds > 0:
            seconds = min(args.observe_seconds, 60.0)
            first = report
            time.sleep(seconds)
            report = sample(repo_root, config_path.resolve())
            report["observation"] = _observation(first, report, seconds)
            if report["overall_health"] in {"healthy", "starting"}:
                stalled_lanes = [
                    item["index"] for item in report["observation"]["lanes"]
                    if item["after_health"] == "healthy"
                    and not item["heartbeat_advanced"]
                    and not item["durable_progress_changed"]
                ]
                if stalled_lanes:
                    report["overall_health"] = "unhealthy"
                    report.setdefault("observation_errors", []).append(
                        f"no heartbeat or durable progress across observation for lanes {stalled_lanes}"
                    )
    except Exception as exc:
        report = {
            "schema": "ipfs_datasets_py/uscode-sparse-graphrag-status@1",
            "as_of": datetime.now(timezone.utc).isoformat(),
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
                f"lane {lane['index']}: {lane['health']} active={tasks['active_task_id'] or '-'} "
                f"completed={tasks['completed_count']} ready={tasks['ready_count']} "
                f"waiting={tasks['waiting_count']} blocked={tasks['blocked_count']}"
            )
            for reason in lane["reasons"]:
                print(f"  ERROR: {reason}")
    health = report.get("overall_health")
    if health in {"healthy", "starting", "completed"}:
        return 0
    if health == "malformed":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
