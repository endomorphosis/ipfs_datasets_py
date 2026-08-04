"""Regression coverage for the PATLAW supervisor health projection."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATUS_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "patent_legal_intelligence" / "status.py"
)


def _load_status_module():
    spec = importlib.util.spec_from_file_location(
        "patent_legal_intelligence_status_under_test",
        _STATUS_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


status_mod = _load_status_module()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _health_fixture(tmp_path: Path, *, now: datetime) -> tuple[Path, Path, Path]:
    state_root = tmp_path / "state"
    shard_root = state_root / "shards" / "0"
    state_dir = shard_root / "state"
    prefix = "patlaw_shard_0"
    managed_log = state_dir / "managed.log"
    historical_log = state_dir / "historical-implementation.log"
    outer_log = shard_root / "logs" / "supervisor.log"
    for path in (managed_log, historical_log, outer_log):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("bounded test log\n", encoding="utf-8")
    old = (now - timedelta(hours=3)).timestamp()
    os.utime(historical_log, (old, old))
    os.utime(outer_log, (old, old))
    _write_json(
        state_dir / f"{prefix}_task_state.json",
        {
            "active_task_id": "",
            "last_implementation_task_id": "PATLAW-074",
            "implementation_in_progress": False,
            "active_phase": "",
            "active_log_path": "",
            "last_implementation_log_path": str(historical_log),
            "heartbeat_at": (now - timedelta(hours=2)).isoformat(),
            "last_progress_at": (now - timedelta(hours=2)).isoformat(),
            "ready_count": 0,
            "selectable_ready_count": 0,
            "eligible_ready_count": 0,
            "waiting_count": 0,
            "blocked_count": 0,
            "completed_count": 57,
            "selection_idle_reason": "no_shard_selectable_ready_tasks",
        },
    )
    _write_json(
        state_dir / f"{prefix}_supervisor_status.json",
        {
            "status": "running",
            "updated_at": now.isoformat(),
            "daemon_pid": 222,
            "log_path": str(managed_log),
            "restart_count": 0,
        },
    )
    (shard_root / "supervisor.pid").write_text("111\n", encoding="utf-8")
    (state_dir / f"{prefix}_managed_daemon.pid").write_text("222\n", encoding="utf-8")
    return state_root, managed_log, historical_log


def _report(monkeypatch, state_root: Path) -> dict[str, object]:
    monkeypatch.setattr(status_mod, "_pid_alive", lambda pid: pid in {111, 222})
    monkeypatch.setattr(
        status_mod,
        "_cmdline",
        lambda pid: (
            "python -m implementation_supervisor --state-prefix patlaw_shard_0"
            if pid == 111
            else "python -m implementation_daemon --state-prefix patlaw_shard_0"
        ),
    )
    return status_mod._shard_health(
        shard=0,
        state_root=state_root,
        heartbeat_limit=120,
        log_limit=600,
        ready_grace=120,
        startup_grace=0,
    )


def test_completed_quiescent_lane_uses_supervisor_and_managed_log_liveness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    state_root, _managed_log, _historical_log = _health_fixture(tmp_path, now=now)

    report = _report(monkeypatch, state_root)

    assert report["health"] == "healthy"
    assert report["reasons"] == []
    assert report["active_task_id"] == ""
    assert report["active_log_age_seconds"] is None
    assert report["quiescent"] is True
    assert report["heartbeat_age_seconds"] < 5
    assert report["task_projection_age_seconds"] > 7000
    assert report["managed_log_age_seconds"] < 5


def test_quiescent_lane_rejects_a_stale_managed_daemon_pass_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    state_root, managed_log, _historical_log = _health_fixture(tmp_path, now=now)
    old = (now - timedelta(minutes=5)).timestamp()
    os.utime(managed_log, (old, old))

    report = _report(monkeypatch, state_root)

    assert report["health"] == "unhealthy"
    assert any("managed daemon pass log is stale" in reason for reason in report["reasons"])


def test_quiescent_lane_requires_parseable_heartbeat_and_managed_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    state_root, _managed_log, _historical_log = _health_fixture(tmp_path, now=now)
    status_path = (
        state_root
        / "shards"
        / "0"
        / "state"
        / "patlaw_shard_0_supervisor_status.json"
    )
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.pop("updated_at")
    status.pop("log_path")
    _write_json(status_path, status)

    report = _report(monkeypatch, state_root)

    assert report["health"] == "unhealthy"
    assert "supervisor heartbeat is missing or unparseable" in report["reasons"]
    assert "managed daemon pass log is missing" in report["reasons"]


def test_active_implementation_still_rejects_a_stale_active_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    state_root, _managed_log, historical_log = _health_fixture(tmp_path, now=now)
    task_path = (
        state_root
        / "shards"
        / "0"
        / "state"
        / "patlaw_shard_0_task_state.json"
    )
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task.update(
        {
            "active_task_id": "PATLAW-999",
            "implementation_in_progress": True,
            "active_phase": "implementing",
            "active_log_path": str(historical_log),
            "ready_count": 1,
            "selectable_ready_count": 1,
            "eligible_ready_count": 1,
            "selection_idle_reason": "",
        }
    )
    _write_json(task_path, task)

    report = _report(monkeypatch, state_root)

    assert report["health"] == "unhealthy"
    assert report["active_task_id"] == "PATLAW-999"
    assert report["quiescent"] is False
    assert any("active implementation log is stale" in reason for reason in report["reasons"])
