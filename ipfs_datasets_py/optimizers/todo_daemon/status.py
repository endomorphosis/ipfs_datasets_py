"""Reusable status-payload helpers for unattended todo daemons."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .engine import utc_now


@dataclass(frozen=True)
class ActiveStatusSnapshot:
    """Current non-heartbeat daemon state for stable heartbeat reporting."""

    state: str = "initializing"
    started_at: str = ""
    target_task: str = ""


def status_started_at(
    previous: Mapping[str, Any],
    *,
    state: str,
    now: str,
    state_key: str = "state",
    started_at_key: str = "state_started_at",
) -> str:
    """Return the preserved or fresh start timestamp for a status state."""

    if str(previous.get(state_key) or "") == state and previous.get(started_at_key):
        return str(previous[started_at_key])
    return now


def status_key_started_at(
    previous: Mapping[str, Any],
    *,
    current_key: str,
    now: str,
    key_field: str = "phase_key",
    started_at_key: str = "phase_started_at",
) -> str:
    """Return a preserved start timestamp when a stable status key has not changed."""

    if str(previous.get(key_field) or "") == current_key and previous.get(started_at_key):
        return str(previous[started_at_key])
    return now


def build_status_phase_key(
    phase: str,
    *,
    cycle_index: Optional[int] = None,
    details: Optional[Mapping[str, Any]] = None,
    attempt_key: str = "proposal_attempt",
    retry_reason_key: str = "retry_reason",
    retry_reason_limit: int = 80,
) -> str:
    """Return a stable phase key for supervisor phase-age accounting."""

    parts: list[str] = []
    if cycle_index is not None:
        parts.append(str(cycle_index))
    parts.append(str(phase))
    source = details or {}
    attempt = source.get(attempt_key)
    retry_reason = source.get(retry_reason_key)
    if attempt is not None:
        parts.append(f"attempt={attempt}")
    if retry_reason:
        limit = max(1, int(retry_reason_limit))
        parts.append(f"retry={str(retry_reason)[:limit]}")
    return "|".join(parts)


def write_status_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    sort_keys: bool = False,
    trailing_newline: bool = False,
) -> None:
    """Atomically write daemon status/progress JSON with ``default=str`` support."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    text = json.dumps(payload, indent=2, default=str, sort_keys=sort_keys)
    if trailing_newline:
        text += "\n"
    try:
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def advance_active_status_snapshot(
    snapshot: ActiveStatusSnapshot,
    *,
    state: str,
    now: str,
    target_task: Optional[str] = None,
    heartbeat_state: str = "heartbeat",
) -> ActiveStatusSnapshot:
    """Advance active non-heartbeat state while preserving same-state start time."""

    if state == heartbeat_state:
        return snapshot
    resolved_target = snapshot.target_task if target_task is None else str(target_task or "")
    if state == snapshot.state and resolved_target == snapshot.target_task and snapshot.started_at:
        started_at = snapshot.started_at
    else:
        started_at = now
    return ActiveStatusSnapshot(
        state=state,
        started_at=started_at,
        target_task=resolved_target,
    )


def build_active_status_payload(
    *,
    state: str,
    snapshot: ActiveStatusSnapshot,
    now: Optional[str] = None,
    pid: Optional[int] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build the common status payload used by hook-driven todo daemons."""

    timestamp = now or utc_now()
    return {
        "updated_at": timestamp,
        "pid": os.getpid() if pid is None else int(pid),
        "state": state,
        "active_state": snapshot.state,
        "active_state_started_at": snapshot.started_at,
        "active_target_task": snapshot.target_task,
        **dict(extra or {}),
    }


def build_heartbeat_status_payload(
    base: Mapping[str, Any],
    *,
    now: Optional[str] = None,
    state: str = "heartbeat",
    timestamp_key: Optional[str] = None,
    updated_at_key: str = "updated_at",
    heartbeat_at_key: str = "heartbeat_at",
    active_state_key: str = "active_state",
    active_state_started_at_key: str = "active_state_started_at",
    active_state_from_key: str = "state",
    active_started_from_key: str = "state_started_at",
    heartbeat_interval_seconds: Optional[float] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Return a heartbeat payload derived from the latest status payload."""

    timestamp = now or utc_now()
    payload = dict(base)
    if timestamp_key:
        payload[timestamp_key] = timestamp
    payload[updated_at_key] = timestamp
    payload[heartbeat_at_key] = timestamp
    payload["state"] = state
    payload[active_state_key] = base.get(active_state_from_key, "")
    payload[active_state_started_at_key] = base.get(active_started_from_key, "")
    if heartbeat_interval_seconds is not None:
        payload["heartbeat_interval_seconds"] = heartbeat_interval_seconds
    payload.update(dict(extra or {}))
    return payload


def build_ready_after_supervisor_repair_status(
    *,
    created_at: str,
    previous_status: Mapping[str, Any],
    repair_state: str,
    supervisor_action: str,
    supervisor_reason: str,
    reset_task_labels: Iterable[str] = (),
    previous_state_keys: Iterable[str] = ("active_state", "state"),
    previous_target_keys: Iterable[str] = ("active_target_task", "target_task"),
    schema_version: int = 1,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Return a status payload for a supervisor-cleared stale worker state.

    Supervisors use this after a dead or stalled worker has been reconciled so
    future status readers no longer see stale ``calling_llm`` or
    ``applying_files`` activity for a process that has already exited.
    """

    previous_state = ""
    for key in previous_state_keys:
        previous_state = str(previous_status.get(str(key)) or "")
        if previous_state:
            break
    previous_target = ""
    for key in previous_target_keys:
        previous_target = str(previous_status.get(str(key)) or "")
        if previous_target:
            break
    payload = {
        "schemaVersion": int(schema_version),
        "updated_at": created_at,
        "state": repair_state,
        "active_state": repair_state,
        "active_state_started_at": created_at,
        "active_target_task": "",
        "previous_state": previous_state,
        "previous_target_task": previous_target,
        "reset_task_labels": [str(label) for label in reset_task_labels],
        "supervisor_action": supervisor_action,
        "supervisor_reason": supervisor_reason,
    }
    payload.update(dict(extra or {}))
    return payload
