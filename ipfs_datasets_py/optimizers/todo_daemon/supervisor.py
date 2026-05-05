"""Reusable supervisor status and watchdog helpers for todo daemons."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .core import (
    ManagedDaemonSpec,
    child_pids,
    first_present,
    now_utc,
    parse_timestamp,
    pid_alive,
    process_args,
    read_json,
    write_json,
)


JsonDict = dict[str, Any]

DEFAULT_WORKTREE_PHASES = frozenset(
    {
        "requesting_worktree_edit",
        "retrying_worktree_edit",
        "repairing_failed_worktree_edit",
        "repairing_failed_tests_before_rollback",
    }
)


def _aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class HeartbeatSnapshot:
    """Parsed daemon heartbeat state."""

    heartbeat_at: Optional[datetime]
    age_seconds: Optional[float]
    pid: Any
    pid_alive: bool
    stale_after_seconds: float

    @property
    def fresh(self) -> bool:
        return self.age_seconds is not None and self.age_seconds <= self.stale_after_seconds

    @property
    def stale(self) -> bool:
        return self.age_seconds is not None and self.age_seconds > self.stale_after_seconds

    def to_payload(self, *, prefix: str = "heartbeat") -> JsonDict:
        return {
            f"{prefix}_at": None if self.heartbeat_at is None else self.heartbeat_at.isoformat(),
            f"{prefix}_age_seconds": None if self.age_seconds is None else round(self.age_seconds, 3),
            "daemon_pid": self.pid,
            "daemon_pid_alive": self.pid_alive,
            f"{prefix}_stale_after_seconds": self.stale_after_seconds,
            f"{prefix}_fresh": self.fresh,
            f"{prefix}_stale": self.stale,
        }


def heartbeat_snapshot(
    status: Mapping[str, Any],
    *,
    stale_after_seconds: float,
    pid_keys: Sequence[str] = ("heartbeat_pid", "pid"),
    timestamp_keys: Sequence[str] = ("heartbeat_at", "updated_at"),
    now: Optional[datetime] = None,
) -> HeartbeatSnapshot:
    """Return parsed heartbeat age, freshness, and process liveness."""

    heartbeat_at = None
    for key in timestamp_keys:
        heartbeat_at = _aware_utc(parse_timestamp(status.get(key)))
        if heartbeat_at is not None:
            break
    now_at = _aware_utc(now) or now_utc()
    age_seconds = None if heartbeat_at is None else max(0.0, (now_at - heartbeat_at).total_seconds())
    pid = None
    for key in pid_keys:
        pid = status.get(key)
        if pid:
            break
    return HeartbeatSnapshot(
        heartbeat_at=heartbeat_at,
        age_seconds=age_seconds,
        pid=pid,
        pid_alive=pid_alive(pid) if pid else False,
        stale_after_seconds=float(stale_after_seconds),
    )


def read_heartbeat_snapshot(
    path: Optional[Path],
    *,
    stale_after_seconds: float,
    pid_keys: Sequence[str] = ("heartbeat_pid", "pid"),
    timestamp_keys: Sequence[str] = ("heartbeat_at", "updated_at"),
    now: Optional[datetime] = None,
) -> HeartbeatSnapshot:
    """Read a status file and return parsed heartbeat state."""

    return heartbeat_snapshot(
        read_json(path),
        stale_after_seconds=stale_after_seconds,
        pid_keys=pid_keys,
        timestamp_keys=timestamp_keys,
        now=now,
    )


def heartbeat_is_stale(
    path: Optional[Path],
    *,
    stale_after_seconds: float,
    now: Optional[datetime] = None,
) -> bool:
    """Return whether a status file heartbeat is present and stale."""

    return read_heartbeat_snapshot(path, stale_after_seconds=stale_after_seconds, now=now).stale


def descendant_processes(root_pid: Any) -> list[JsonDict]:
    """Return descendant processes for a root pid using the shared process primitives."""

    try:
        root = int(root_pid)
    except Exception:
        return []
    stack = list(child_pids(root))
    seen: set[int] = set()
    found: list[JsonDict] = []
    while stack:
        pid = stack.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        found.append({"pid": pid, "cmdline": process_args(pid)})
        stack.extend(child_pids(pid))
    return found


def active_codex_exec_workers(root_pid: Any) -> list[JsonDict]:
    """Return active Codex worker subprocesses below a daemon pid."""

    workers: list[JsonDict] = []
    for item in descendant_processes(root_pid):
        cmdline = str(item.get("cmdline") or "").lower()
        normalized = " " + " ".join(cmdline.split())
        if "codex" in cmdline and " exec" in normalized:
            workers.append(item)
    return workers


def worktree_phase_worker_status(
    current: Mapping[str, Any],
    daemon_pid: Any = None,
    threshold_seconds: float = 0.0,
    *,
    phases: frozenset[str] = DEFAULT_WORKTREE_PHASES,
    now: Optional[datetime] = None,
) -> JsonDict:
    """Report whether a worktree-edit phase appears stuck without a worker."""

    phase = str(current.get("phase") or "")
    if phase not in phases:
        return {"required": False, "phase": phase}
    started = _aware_utc(
        parse_timestamp(first_present(current.get("phase_started_at"), current.get("phase_updated_at")))
    )
    now_at = _aware_utc(now) or now_utc()
    age = None if started is None else max(0.0, (now_at - started).total_seconds())
    root_pid = daemon_pid or current.get("heartbeat_pid") or current.get("pid")
    descendants = descendant_processes(root_pid)
    workers = [
        item
        for item in descendants
        if "codex" in str(item.get("cmdline") or "").lower()
        and " exec" in (" " + " ".join(str(item.get("cmdline") or "").lower().split()))
    ]
    stalled = bool(age is not None and threshold_seconds > 0 and age >= threshold_seconds and not workers)
    return {
        "required": True,
        "phase": phase,
        "phase_age_seconds": None if age is None else round(age, 3),
        "threshold_seconds": float(threshold_seconds),
        "active_worker_pids": [item.get("pid") for item in workers],
        "active_worker_count": len(workers),
        "descendant_count": len(descendants),
        "stalled_without_active_worker": stalled,
    }


@dataclass(frozen=True)
class SupervisorStatusContext:
    """Reusable context for rendering supervisor status payloads."""

    spec: ManagedDaemonSpec
    schema: str = ""
    static_fields: Mapping[str, Any] = field(default_factory=dict)

    def payload(
        self,
        status: str,
        *,
        run_id: str = "",
        log_path: str = "",
        daemon_pid: Any = None,
        restart_count: int = 0,
        last_exit_code: Any = None,
        supervisor_pid: Optional[int] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> JsonDict:
        return build_supervisor_status_payload(
            self.spec,
            status=status,
            schema=self.schema,
            static_fields=self.static_fields,
            run_id=run_id,
            log_path=log_path,
            daemon_pid=daemon_pid,
            restart_count=restart_count,
            last_exit_code=last_exit_code,
            supervisor_pid=supervisor_pid,
            extra=extra,
        )

    def write(self, status: str, **kwargs: Any) -> JsonDict:
        payload = self.payload(status, **kwargs)
        path = self.spec.resolve(self.spec.supervisor_status_path)
        assert path is not None
        write_json(path, payload)
        return payload


def build_supervisor_status_payload(
    spec: ManagedDaemonSpec,
    *,
    status: str,
    schema: str = "",
    static_fields: Optional[Mapping[str, Any]] = None,
    run_id: str = "",
    log_path: str = "",
    daemon_pid: Any = None,
    restart_count: int = 0,
    last_exit_code: Any = None,
    supervisor_pid: Optional[int] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> JsonDict:
    """Build the common supervisor JSON status payload."""

    payload: JsonDict = {
        "schema": schema or f"{spec.schema}.supervisor",
        "status": status,
        "updated_at": now_utc().isoformat(),
        "repo_root": str(spec.repo_root),
        "supervisor_pid": os.getpid() if supervisor_pid is None else supervisor_pid,
        "daemon_pid": daemon_pid,
        "restart_count": int(restart_count),
        "run_id": run_id,
        "log_path": log_path,
        "current_status_path": spec.repo_relative(spec.status_path),
        "progress_path": spec.repo_relative(spec.progress_path),
        "child_pid_path": spec.repo_relative(spec.child_pid_path),
        "supervisor_lock_path": spec.repo_relative(spec.supervisor_lock_path),
    }
    if last_exit_code is not None:
        payload["last_exit_code"] = last_exit_code
    if static_fields:
        payload.update(dict(static_fields))
    if extra:
        payload.update(dict(extra))
    return payload
