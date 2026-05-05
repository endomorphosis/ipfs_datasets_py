"""Reusable status-payload helpers for unattended todo daemons."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

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
