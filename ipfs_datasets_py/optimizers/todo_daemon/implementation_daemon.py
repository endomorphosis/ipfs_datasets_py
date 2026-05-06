from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import pid_alive as _shared_pid_alive
from .core import process_args as _shared_process_args
from .engine import atomic_write_json as _shared_atomic_write_json
from .runner import TodoDaemonHooks, TodoDaemonRunner

REPO_ROOT = Path.cwd()

logger = logging.getLogger("ipfs_datasets_py.optimizers.todo_daemon.implementation_daemon")

TASK_HEADER_PREFIX = "## PORTAL-"
DEFAULT_TRACKS = ["platform", "data", "ui", "mobile", "wallet", "collab", "pwa", "ops"]
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DEFAULT_IMPLEMENTATION_TIMEOUT_SECONDS = 1800.0
RECENT_NO_CHANGE_COOLDOWN_SECONDS = 1800.0
NO_CHANGE_SELECTION_PENALTY = 50
UNRESOLVED_MERGE_SELECTION_PENALTY = 1000
SHARED_WORKTREE_PATHS = ("wallet_interface/ui/node_modules",)
WORKTREE_SUBMODULE_PATHS = ("ipfs_datasets_py",)
EPHEMERAL_WORKTREE_PATHS = (
    *SHARED_WORKTREE_PATHS,
    *WORKTREE_SUBMODULE_PATHS,
    ".pytest_cache",
    "test-results",
    "wallet_interface/__pycache__",
    "wallet_interface/ui/dist",
    "wallet_interface/ui/playwright-report",
    "wallet_interface/ui/test-results",
    "wallet_interface/ui/artifacts/ui-iterations/latest",
    "wallet_interface/ui/artifacts/ui-screenshots/latest",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def split_csv(value: str) -> list[str]:
    raw = [item.strip() for item in value.split(",")]
    return [item for item in raw if item and item.lower() not in {"none", "n/a"}]


def normalize_status(value: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if lowered in {"done", "complete", "completed"}:
        return "completed"
    if lowered in {"blocked", "on_hold"}:
        return "blocked"
    if lowered in {"active", "in_progress"}:
        return "in_progress"
    if lowered in {"ready", "todo", "queued", ""}:
        return "todo"
    return lowered


def normalize_task_header_prefix(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("## "):
        return stripped
    return f"## {stripped}"


def write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)
        os.replace(temp_path, path)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def write_json_atomic(path: Path, payload: Any) -> None:
    if isinstance(payload, dict):
        _shared_atomic_write_json(path, payload)
        return
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    return _shared_pid_alive(pid)


def process_command_line(pid: int) -> str:
    return _shared_process_args(pid)


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class PortalTask:
    task_id: str
    title: str
    status: str
    completion: str
    priority: str
    track: str
    depends_on: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)
    acceptance: str = ""
    source_line: int = 0


@dataclass
class PortalTaskState:
    heartbeat_at: str = ""
    last_progress_at: str = ""
    active_task_id: str = ""
    active_task_title: str = ""
    active_task_track: str = ""
    active_task_started_at: str = ""
    recommended_task_id: str = ""
    recommended_actions: list[str] = field(default_factory=list)
    completed_task_ids: list[str] = field(default_factory=list)
    ready_task_ids: list[str] = field(default_factory=list)
    waiting_task_ids: list[str] = field(default_factory=list)
    blocked_task_ids: list[str] = field(default_factory=list)
    task_statuses: dict[str, str] = field(default_factory=dict)
    task_artifacts: dict[str, list[str]] = field(default_factory=dict)
    task_validation: dict[str, list[str]] = field(default_factory=dict)
    implementation_attempts: dict[str, int] = field(default_factory=dict)
    last_implementation_task_id: str = ""
    last_implementation_started_at: str = ""
    last_implementation_finished_at: str = ""
    last_implementation_returncode: int | None = None
    last_implementation_log_path: str = ""
    last_implementation_worktree_path: str = ""
    last_implementation_branch: str = ""
    last_implementation_commit: str = ""
    last_merge_started_at: str = ""
    last_merge_finished_at: str = ""
    last_merge_branch: str = ""
    last_merge_commit: str = ""
    last_merge_returncode: int | None = None
    last_merge_error: str = ""
    completed_count: int = 0
    ready_count: int = 0
    waiting_count: int = 0
    blocked_count: int = 0
    task_count: int = 0
    strategy_generation: int = 0

    def save(self, path: Path) -> None:
        write_json_atomic(path, asdict(self))

    @classmethod
    def load(cls, path: Path) -> "PortalTaskState":
        if not path.exists():
            return cls()
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return cls()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return cls()
        if not isinstance(payload, dict):
            return cls()
        return cls(
            heartbeat_at=str(payload.get("heartbeat_at") or ""),
            last_progress_at=str(payload.get("last_progress_at") or ""),
            active_task_id=str(payload.get("active_task_id") or ""),
            active_task_title=str(payload.get("active_task_title") or ""),
            active_task_track=str(payload.get("active_task_track") or ""),
            active_task_started_at=str(payload.get("active_task_started_at") or ""),
            recommended_task_id=str(payload.get("recommended_task_id") or ""),
            recommended_actions=[str(item) for item in payload.get("recommended_actions", []) or []],
            completed_task_ids=[str(item) for item in payload.get("completed_task_ids", []) or []],
            ready_task_ids=[str(item) for item in payload.get("ready_task_ids", []) or []],
            waiting_task_ids=[str(item) for item in payload.get("waiting_task_ids", []) or []],
            blocked_task_ids=[str(item) for item in payload.get("blocked_task_ids", []) or []],
            task_statuses={str(key): str(value) for key, value in (payload.get("task_statuses") or {}).items()},
            task_artifacts={
                str(key): [str(item) for item in value]
                for key, value in (payload.get("task_artifacts") or {}).items()
                if isinstance(value, list)
            },
            task_validation={
                str(key): [str(item) for item in value]
                for key, value in (payload.get("task_validation") or {}).items()
                if isinstance(value, list)
            },
            implementation_attempts={
                str(key): int(value)
                for key, value in (payload.get("implementation_attempts") or {}).items()
                if str(value).isdigit()
            },
            last_implementation_task_id=str(payload.get("last_implementation_task_id") or ""),
            last_implementation_started_at=str(payload.get("last_implementation_started_at") or ""),
            last_implementation_finished_at=str(payload.get("last_implementation_finished_at") or ""),
            last_implementation_returncode=(
                int(payload["last_implementation_returncode"])
                if payload.get("last_implementation_returncode") is not None
                else None
            ),
            last_implementation_log_path=str(payload.get("last_implementation_log_path") or ""),
            last_implementation_worktree_path=str(payload.get("last_implementation_worktree_path") or ""),
            last_implementation_branch=str(payload.get("last_implementation_branch") or ""),
            last_implementation_commit=str(payload.get("last_implementation_commit") or ""),
            last_merge_started_at=str(payload.get("last_merge_started_at") or ""),
            last_merge_finished_at=str(payload.get("last_merge_finished_at") or ""),
            last_merge_branch=str(payload.get("last_merge_branch") or ""),
            last_merge_commit=str(payload.get("last_merge_commit") or ""),
            last_merge_returncode=(
                int(payload["last_merge_returncode"])
                if payload.get("last_merge_returncode") is not None
                else None
            ),
            last_merge_error=str(payload.get("last_merge_error") or ""),
            completed_count=int(payload.get("completed_count") or 0),
            ready_count=int(payload.get("ready_count") or 0),
            waiting_count=int(payload.get("waiting_count") or 0),
            blocked_count=int(payload.get("blocked_count") or 0),
            task_count=int(payload.get("task_count") or 0),
            strategy_generation=int(payload.get("strategy_generation") or 0),
        )


def parse_task_file(path: Path, task_header_prefix: str = TASK_HEADER_PREFIX) -> list[PortalTask]:
    task_header_prefix = normalize_task_header_prefix(task_header_prefix)
    lines = path.read_text(encoding="utf-8").splitlines()
    tasks: list[PortalTask] = []
    current_id = ""
    current_title = ""
    current_line = 0
    block: list[str] = []

    def flush() -> None:
        nonlocal block, current_id, current_title, current_line
        if not current_id:
            return
        metadata: dict[str, str] = {}
        for line in block:
            stripped = line.strip()
            if not stripped.startswith("- ") or ":" not in stripped:
                continue
            key, value = stripped[2:].split(":", 1)
            metadata[key.strip().lower()] = value.strip()
        tasks.append(
            PortalTask(
                task_id=current_id,
                title=current_title,
                status=normalize_status(metadata.get("status", "todo")),
                completion=str(metadata.get("completion", "manual")).strip().lower(),
                priority=str(metadata.get("priority", "P2")).strip().upper(),
                track=str(metadata.get("track", "ops")).strip().lower(),
                depends_on=split_csv(metadata.get("depends on", "")),
                outputs=split_csv(metadata.get("outputs", "")),
                validation=[item.strip() for item in metadata.get("validation", "").split(";") if item.strip()],
                acceptance=str(metadata.get("acceptance", "")).strip(),
                source_line=current_line,
            )
        )
        current_id = ""
        current_title = ""
        current_line = 0
        block = []

    for index, line in enumerate(lines, start=1):
        if line.startswith(task_header_prefix):
            flush()
            header = line[3:].strip()
            parts = header.split(" ", 1)
            if len(parts) == 1:
                current_id = parts[0]
                current_title = ""
            else:
                current_id, current_title = parts[0], parts[1].strip()
            current_line = index
            block = []
            continue
        if current_id:
            block.append(line)

    flush()
    return tasks


class PortalImplementationDaemon:
    shared_todo_runner_class = TodoDaemonRunner
    shared_todo_hooks_class = TodoDaemonHooks

    def __init__(
        self,
        *,
        todo_path: Path,
        state_path: Path,
        strategy_path: Path,
        events_path: Path,
        repo_root: Path | None = None,
        task_header_prefix: str = TASK_HEADER_PREFIX,
        implement: bool = False,
        implementation_command: str | None = None,
        implementation_timeout: float = DEFAULT_IMPLEMENTATION_TIMEOUT_SECONDS,
        implementation_log_dir: Path | None = None,
        use_ephemeral_worktree: bool = False,
        worktree_root: Path | None = None,
    ) -> None:
        self.todo_path = todo_path
        self.state_path = state_path
        self.strategy_path = strategy_path
        self.events_path = events_path
        self.repo_root = repo_root or REPO_ROOT
        self.task_header_prefix = normalize_task_header_prefix(task_header_prefix)
        self.implement = implement
        self.implementation_command = implementation_command
        self.implementation_timeout = implementation_timeout
        self.implementation_log_dir = implementation_log_dir or self.state_path.parent / "implementation_logs"
        self.use_ephemeral_worktree = use_ephemeral_worktree
        self.worktree_root = worktree_root or Path(tempfile.gettempdir()) / "211-ai-implementation-worktrees"

    def load_strategy(self) -> dict[str, Any]:
        defaults = {
            "generation": 0,
            "focus_tracks": DEFAULT_TRACKS,
            "blocked_tasks": [],
            "deprioritized_tasks": [],
            "last_rewrite_at": "",
            "last_rewrite_reason": "",
        }
        if not self.strategy_path.exists():
            write_json_atomic(self.strategy_path, defaults)
            return defaults
        payload = load_json_dict(self.strategy_path)
        if payload is None:
            logger.warning("Strategy file is missing or invalid JSON; using defaults: %s", self.strategy_path)
            return defaults.copy()
        merged = {**defaults, **payload}
        merged["focus_tracks"] = [str(item).lower() for item in merged.get("focus_tracks", DEFAULT_TRACKS)]
        merged["blocked_tasks"] = [str(item) for item in merged.get("blocked_tasks", [])]
        merged["deprioritized_tasks"] = [str(item) for item in merged.get("deprioritized_tasks", [])]
        return merged

    def run_once(self) -> dict[str, Any]:
        tasks = parse_task_file(self.todo_path, self.task_header_prefix)
        if not tasks:
            raise RuntimeError(f"No tasks found in {self.todo_path}")
        previous = PortalTaskState.load(self.state_path)
        strategy = self.load_strategy()
        now = utc_now()
        merge_reconciliation = self._reconcile_failed_merges()
        unresolved_merge_failures = self._unresolved_merge_failures_by_task()
        recent_outcomes = self._latest_implementation_finished_by_task()

        previous_completed = set(previous.completed_task_ids)
        completed_set: set[str] = set()
        newly_completed: list[str] = []
        resolved_statuses: dict[str, str] = {}
        task_artifacts: dict[str, list[str]] = {}

        for task in tasks:
            existing_outputs = [item for item in task.outputs if (self.repo_root / item).exists()]
            task_artifacts[task.task_id] = existing_outputs
            unresolved_merge_failure = (
                task.task_id in unresolved_merge_failures
                or self._has_unresolved_merge_failure(task, previous)
            )
            artifact_complete = (
                task.completion == "artifact"
                and bool(task.outputs)
                and len(existing_outputs) == len(task.outputs)
                and not unresolved_merge_failure
            )
            if task.status == "completed" or artifact_complete:
                resolved_statuses[task.task_id] = "completed"
                completed_set.add(task.task_id)
                if task.task_id not in previous_completed:
                    newly_completed.append(task.task_id)
                continue
            if task.task_id in strategy.get("blocked_tasks", []) or task.status == "blocked":
                resolved_statuses[task.task_id] = "blocked"
                continue
            unresolved_deps = [dep for dep in task.depends_on if dep not in completed_set]
            if unresolved_deps:
                resolved_statuses[task.task_id] = "waiting"
                continue
            resolved_statuses[task.task_id] = "ready"

        selected = self._select_next_task(tasks, resolved_statuses, strategy, unresolved_merge_failures, recent_outcomes)
        state = PortalTaskState.load(self.state_path)
        state.heartbeat_at = now
        if newly_completed or not state.last_progress_at:
            state.last_progress_at = now
        state.completed_task_ids = sorted(completed_set)
        state.completed_count = len(state.completed_task_ids)
        state.ready_task_ids = [task.task_id for task in tasks if resolved_statuses[task.task_id] == "ready"]
        state.waiting_task_ids = [task.task_id for task in tasks if resolved_statuses[task.task_id] == "waiting"]
        state.blocked_task_ids = [task.task_id for task in tasks if resolved_statuses[task.task_id] == "blocked"]
        state.ready_count = len(state.ready_task_ids)
        state.waiting_count = len(state.waiting_task_ids)
        state.blocked_count = len(state.blocked_task_ids)
        state.task_count = len(tasks)
        state.task_statuses = resolved_statuses
        state.task_artifacts = task_artifacts
        state.task_validation = {task.task_id: task.validation for task in tasks if task.validation}
        state.strategy_generation = int(strategy.get("generation", 0))
        state.implementation_attempts = previous.implementation_attempts
        state.last_implementation_task_id = previous.last_implementation_task_id
        state.last_implementation_started_at = previous.last_implementation_started_at
        state.last_implementation_finished_at = previous.last_implementation_finished_at
        state.last_implementation_returncode = previous.last_implementation_returncode
        state.last_implementation_log_path = previous.last_implementation_log_path
        state.last_implementation_worktree_path = previous.last_implementation_worktree_path
        state.last_implementation_branch = previous.last_implementation_branch
        state.last_implementation_commit = previous.last_implementation_commit
        state.last_merge_started_at = previous.last_merge_started_at
        state.last_merge_finished_at = previous.last_merge_finished_at
        state.last_merge_branch = previous.last_merge_branch
        state.last_merge_commit = previous.last_merge_commit
        state.last_merge_returncode = previous.last_merge_returncode
        state.last_merge_error = previous.last_merge_error

        if selected is not None:
            if state.active_task_id != selected.task_id:
                state.active_task_started_at = now
                state.last_progress_at = now
                self._record_event(
                    "task_selected",
                    {
                        "task_id": selected.task_id,
                        "title": selected.title,
                        "track": selected.track,
                    },
                )
            state.active_task_id = selected.task_id
            state.active_task_title = selected.title
            state.active_task_track = selected.track
            state.recommended_task_id = selected.task_id
            state.recommended_actions = self._build_recommended_actions(selected)
        else:
            state.active_task_id = ""
            state.active_task_title = ""
            state.active_task_track = ""
            state.active_task_started_at = ""
            state.recommended_task_id = ""
            state.recommended_actions = []

        state.save(self.state_path)
        for task_id in newly_completed:
            self._record_event("task_completed", {"task_id": task_id})
        implementation_result: dict[str, Any] | None = None
        if self.implement and selected is not None and resolved_statuses.get(selected.task_id) == "ready":
            unresolved_for_selected = unresolved_merge_failures.get(selected.task_id)
            if unresolved_for_selected is not None:
                implementation_result = {
                    "skipped": True,
                    "reason": "unresolved_merge_failure",
                    "task_id": selected.task_id,
                    "branch": str(unresolved_for_selected.get("branch") or ""),
                    "implementation_commit": str(unresolved_for_selected.get("implementation_commit") or ""),
                }
                self._record_event("implementation_skipped", implementation_result)
            elif self._task_has_recent_no_change_outcome(selected.task_id, recent_outcomes):
                implementation_result = {
                    "skipped": True,
                    "reason": "recent_no_change",
                    "task_id": selected.task_id,
                    "last_attempt": int((recent_outcomes.get(selected.task_id) or {}).get("attempt") or 0),
                }
                self._record_event("implementation_skipped", implementation_result)
            else:
                implementation_result = self._run_implementation(selected, state)
        self._record_event(
            "daemon_pass",
            {
                "completed_count": state.completed_count,
                "ready_count": state.ready_count,
                "waiting_count": state.waiting_count,
                "blocked_count": state.blocked_count,
                "active_task_id": state.active_task_id,
            },
        )
        return {
            "task_count": state.task_count,
            "completed_count": state.completed_count,
            "ready_count": state.ready_count,
            "waiting_count": state.waiting_count,
            "blocked_count": state.blocked_count,
            "active_task_id": state.active_task_id,
            "state_path": str(self.state_path),
            "strategy_path": str(self.strategy_path),
            "events_path": str(self.events_path),
            "implementation_result": implementation_result,
            "merge_reconciliation": merge_reconciliation,
        }

    def _run_implementation(self, task: PortalTask, state: PortalTaskState) -> dict[str, Any]:
        inflight = self._find_live_inflight_implementation()
        if inflight is not None:
            result = {
                "skipped": True,
                "reason": "inflight_process",
                "task_id": str(inflight.get("task_id") or task.task_id),
                "attempt": int(inflight.get("attempt") or 0),
                "worktree_path": str(inflight.get("worktree_path") or ""),
            }
            self._record_event("implementation_skipped", result)
            return result

        started_at = utc_now()
        attempt = state.implementation_attempts.get(task.task_id, 0) + 1
        lock_path = self._implementation_lock_path()
        lock_metadata = self._build_implementation_lock_metadata(task, attempt, started_at)
        lock_fd, lock_reason, existing_lock = self._try_acquire_lock(
            lock_path,
            lock_kind="implementation",
            owner_active=self._implementation_lock_owner_is_active,
        )
        if lock_fd is None:
            result = {
                "skipped": True,
                "reason": lock_reason,
                "task_id": task.task_id,
                "attempt": attempt,
            }
            if existing_lock:
                result["lock_owner_pid"] = int(existing_lock.get("pid") or 0)
                result["lock_owner_task_id"] = str(existing_lock.get("task_id") or "")
            self._record_event("implementation_skipped", result)
            return result

        acquired_lock = True
        log_path = self.implementation_log_dir / f"{task.task_id.lower()}-attempt-{attempt}.log"
        prompt = self._build_implementation_prompt(task, attempt)
        workspace_path = self.repo_root
        command = self._build_implementation_command(workspace_path)
        result: dict[str, Any]
        validation_result: dict[str, Any] = {
            "attempted": False,
            "passed": True,
            "returncode": 0,
            "results": [],
            "reason": "not_run",
        }

        try:
            self._write_lock_metadata(lock_fd, lock_metadata)
            if self.use_ephemeral_worktree:
                return self._run_implementation_in_ephemeral_worktree(
                    task=task,
                    state=state,
                    attempt=attempt,
                    started_at=started_at,
                    log_path=log_path,
                    prompt=prompt,
                )
            self.implementation_log_dir.mkdir(parents=True, exist_ok=True)
            self._record_event(
                "implementation_started",
                {
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "command": command,
                    "log_path": str(log_path),
                },
            )
            with log_path.open("w", encoding="utf-8") as log_fh:
                log_fh.write(f"Task: {task.task_id} {task.title}\n")
                log_fh.write(f"Started: {started_at}\n")
                log_fh.write(f"Command: {' '.join(shlex.quote(item) for item in command)}\n\n")
                log_fh.flush()
                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    cwd=workspace_path,
                    timeout=self.implementation_timeout,
                    check=False,
                )
            effective_returncode = completed.returncode
            if completed.returncode == 0:
                validation_result = self._run_validation_commands(workspace_path, task, log_path)
                if not validation_result.get("passed", False):
                    effective_returncode = int(validation_result.get("returncode") or 1)
            finished_at = utc_now()
            state.implementation_attempts[task.task_id] = attempt
            state.last_implementation_task_id = task.task_id
            state.last_implementation_started_at = started_at
            state.last_implementation_finished_at = finished_at
            state.last_implementation_returncode = effective_returncode
            state.last_implementation_log_path = str(log_path)
            state.last_progress_at = finished_at
            state.save(self.state_path)
            result = {
                "task_id": task.task_id,
                "attempt": attempt,
                "returncode": effective_returncode,
                "log_path": str(log_path),
                "validation_result": validation_result,
            }
            self._record_event("implementation_finished", result)
            return result
        except subprocess.TimeoutExpired:
            finished_at = utc_now()
            state.implementation_attempts[task.task_id] = attempt
            state.last_implementation_task_id = task.task_id
            state.last_implementation_started_at = started_at
            state.last_implementation_finished_at = finished_at
            state.last_implementation_returncode = 124
            state.last_implementation_log_path = str(log_path)
            state.save(self.state_path)
            result = {
                "task_id": task.task_id,
                "attempt": attempt,
                "returncode": 124,
                "log_path": str(log_path),
                "error": "timeout",
            }
            self._record_event("implementation_finished", result)
            return result
        finally:
            try:
                if acquired_lock and lock_path.exists():
                    lock_path.unlink()
            except OSError:
                logger.warning("Failed to remove implementation lock %s", lock_path)

    def _run_implementation_in_ephemeral_worktree(
        self,
        *,
        task: PortalTask,
        state: PortalTaskState,
        attempt: int,
        started_at: str,
        log_path: Path,
        prompt: str,
    ) -> dict[str, Any]:
        self.implementation_log_dir.mkdir(parents=True, exist_ok=True)
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        safe_task_id = task.task_id.lower().replace("/", "-")
        attempt_stamp = int(time.time())
        worktree_path = self.worktree_root / f"{safe_task_id}-attempt-{attempt}-{attempt_stamp}"
        branch_name = f"implementation/{safe_task_id}-attempt-{attempt}-{attempt_stamp}"
        baseline_ref = ""
        implementation_commit = ""
        merge_result: dict[str, Any] = {"merged": False, "reason": "not_attempted"}
        validation_result: dict[str, Any] = {
            "attempted": False,
            "passed": True,
            "returncode": 0,
            "results": [],
            "reason": "not_run",
        }
        cleanup_result: dict[str, Any] = {"cleaned": False, "reason": "not_attempted"}
        command: list[str] = []
        returncode = 1
        commit_result: dict[str, Any] = {"committed": False}

        try:
            baseline_ref = self._create_seeded_worktree(worktree_path, branch_name)
            command = self._build_implementation_command(worktree_path)
            self._record_event(
                "implementation_started",
                {
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "command": command,
                    "log_path": str(log_path),
                    "worktree_path": str(worktree_path),
                    "branch": branch_name,
                    "baseline_ref": baseline_ref,
                },
            )
            with log_path.open("w", encoding="utf-8") as log_fh:
                log_fh.write(f"Task: {task.task_id} {task.title}\n")
                log_fh.write(f"Started: {started_at}\n")
                log_fh.write(f"Workspace: {worktree_path}\n")
                log_fh.write(f"Branch: {branch_name}\n")
                log_fh.write(f"Baseline: {baseline_ref}\n")
                log_fh.write(f"Command: {' '.join(shlex.quote(item) for item in command)}\n\n")
                log_fh.flush()
                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    cwd=worktree_path,
                    timeout=self.implementation_timeout,
                    check=False,
            )
            returncode = completed.returncode
            if returncode == 0:
                self._prepare_worktree_for_validation(worktree_path)
                validation_result = self._run_validation_commands(worktree_path, task, log_path)
                if validation_result.get("passed", False):
                    commit_result = self._commit_worktree_changes(worktree_path, task, attempt)
                    implementation_commit = str(commit_result.get("commit", ""))
                    if implementation_commit:
                        merge_result = self._merge_branch_to_main(branch_name, task, attempt)
                        if merge_result.get("merged"):
                            cleanup_result = self._cleanup_merged_worktree(worktree_path, branch_name)
                        else:
                            returncode = int(merge_result.get("returncode") or 1)
                    elif commit_result.get("reason") == "no_changes":
                        cleanup_result = self._cleanup_merged_worktree(worktree_path, branch_name)
                else:
                    returncode = int(validation_result.get("returncode") or 1)
        except subprocess.TimeoutExpired:
            returncode = 124
            self._record_event(
                "implementation_timeout",
                {"task_id": task.task_id, "attempt": attempt, "worktree_path": str(worktree_path)},
            )
        finished_at = utc_now()
        state.implementation_attempts[task.task_id] = attempt
        state.last_implementation_task_id = task.task_id
        state.last_implementation_started_at = started_at
        state.last_implementation_finished_at = finished_at
        state.last_implementation_returncode = returncode
        state.last_implementation_log_path = str(log_path)
        state.last_implementation_worktree_path = str(worktree_path)
        state.last_implementation_branch = branch_name
        state.last_implementation_commit = implementation_commit
        state.last_merge_started_at = str(merge_result.get("started_at") or "")
        state.last_merge_finished_at = str(merge_result.get("finished_at") or "")
        state.last_merge_branch = branch_name if merge_result.get("merged") or merge_result.get("attempted") else ""
        state.last_merge_commit = str(merge_result.get("merge_commit") or "")
        state.last_merge_returncode = (
            int(merge_result["returncode"]) if merge_result.get("returncode") is not None else None
        )
        state.last_merge_error = str(merge_result.get("stderr") or merge_result.get("reason") or "")
        state.last_progress_at = finished_at
        state.save(self.state_path)
        result = {
            "task_id": task.task_id,
            "attempt": attempt,
            "returncode": returncode,
            "log_path": str(log_path),
            "worktree_path": str(worktree_path),
            "branch": branch_name,
            "baseline_ref": baseline_ref,
            "commit_result": commit_result,
            "implementation_commit": implementation_commit,
            "merge_result": merge_result,
            "validation_result": validation_result,
            "cleanup_result": cleanup_result,
        }
        self._record_event("implementation_finished", result)
        return result

    def _create_seeded_worktree(self, worktree_path: Path, branch_name: str) -> str:
        self._run_git(["worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"], cwd=self.repo_root)
        baseline_ref = self._run_git(["rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()
        self._initialize_worktree_submodules(worktree_path)
        self._link_shared_worktree_paths(worktree_path)
        return baseline_ref

    def _initialize_worktree_submodules(self, worktree_path: Path) -> None:
        for relative in WORKTREE_SUBMODULE_PATHS:
            if not self._worktree_declares_submodule(worktree_path, relative):
                continue
            if self._link_local_worktree_submodule(worktree_path, relative):
                continue
            self._run_git(["submodule", "update", "--init", "--recursive", "--", relative], cwd=worktree_path)

    def _link_local_worktree_submodule(self, worktree_path: Path, relative: str) -> bool:
        source = (self.repo_root / relative).resolve()
        if not source.exists():
            return False
        target = worktree_path / relative
        if target.is_symlink():
            if target.resolve() == source:
                return True
            target.unlink()
        elif target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.symlink_to(source, target_is_directory=source.is_dir())
        return True

    def _worktree_declares_submodule(self, worktree_path: Path, relative: str) -> bool:
        gitmodules = worktree_path / ".gitmodules"
        if not gitmodules.exists():
            return False
        result = subprocess.run(
            ["git", "config", "--file", str(gitmodules), "--get-regexp", r"^submodule\..*\.path$"],
            cwd=worktree_path,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        return any(line.split(maxsplit=1)[-1].strip() == relative for line in result.stdout.splitlines())

    def _link_shared_worktree_paths(self, worktree_path: Path) -> None:
        for relative in SHARED_WORKTREE_PATHS:
            source = (self.repo_root / relative).resolve()
            if not source.exists():
                continue
            target = worktree_path / relative
            if target.is_symlink():
                if target.resolve() == source:
                    continue
                target.unlink()
            elif target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source, target_is_directory=source.is_dir())

    def _prepare_worktree_for_validation(self, worktree_path: Path) -> None:
        self._initialize_worktree_submodules(worktree_path)
        self._link_shared_worktree_paths(worktree_path)

    def _commit_worktree_changes(self, worktree_path: Path, task: PortalTask, attempt: int) -> dict[str, Any]:
        self._restore_ephemeral_worktree_paths_for_commit(worktree_path)
        self._run_git(["add", "-A"], cwd=worktree_path)
        status = self._run_git(["status", "--porcelain"], cwd=worktree_path).stdout.strip()
        if not status:
            return {"committed": False, "reason": "no_changes"}
        self._run_git(
            [
                "-c",
                "user.name=Implementation Daemon",
                "-c",
                "user.email=implementation-daemon@example.invalid",
                "commit",
                "-m",
                f"{task.task_id}: {task.title or 'implementation attempt'}",
                "-m",
                f"Attempt: {attempt}",
            ],
            cwd=worktree_path,
        )
        commit_ref = self._run_git(["rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()
        return {"committed": True, "commit": commit_ref, "status": status}

    def _restore_ephemeral_worktree_paths_for_commit(self, worktree_path: Path) -> None:
        for relative in EPHEMERAL_WORKTREE_PATHS:
            target = worktree_path / relative
            if relative in WORKTREE_SUBMODULE_PATHS and target.is_symlink():
                target.unlink()
            if self._path_tracked_in_repo(worktree_path, relative):
                self._run_git(["restore", "--source=HEAD", "--staged", "--worktree", "--", relative], cwd=worktree_path)
                continue
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)

    def _path_tracked_in_repo(self, cwd: Path, relative: str) -> bool:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def _run_validation_commands(self, workspace_path: Path, task: PortalTask, log_path: Path) -> dict[str, Any]:
        if not task.validation:
            return {
                "attempted": False,
                "passed": True,
                "returncode": 0,
                "results": [],
                "reason": "no_commands",
            }

        results: list[dict[str, Any]] = []
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_fh:
            log_fh.write("\nValidation:\n")
            for command in task.validation:
                started_at = utc_now()
                log_fh.write(f"$ {command}\n")
                log_fh.flush()
                try:
                    completed = subprocess.run(
                        ["/bin/bash", "-lc", command],
                        cwd=workspace_path,
                        text=True,
                        stdout=log_fh,
                        stderr=subprocess.STDOUT,
                        timeout=self.implementation_timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    results.append(
                        {
                            "command": command,
                            "started_at": started_at,
                            "finished_at": utc_now(),
                            "returncode": 124,
                            "timed_out": True,
                        }
                    )
                    log_fh.write(f"[validation timed out] timeout={self.implementation_timeout}\n")
                    log_fh.flush()
                    return {
                        "attempted": True,
                        "passed": False,
                        "returncode": 124,
                        "results": results,
                        "failed_command": command,
                        "error": "timeout",
                    }
                result = {
                    "command": command,
                    "started_at": started_at,
                    "finished_at": utc_now(),
                    "returncode": completed.returncode,
                }
                results.append(result)
                if completed.returncode != 0:
                    log_fh.write(f"[validation failed] returncode={completed.returncode}\n")
                    log_fh.flush()
                    return {
                        "attempted": True,
                        "passed": False,
                        "returncode": completed.returncode,
                        "results": results,
                        "failed_command": command,
                    }
            log_fh.write("[validation passed]\n")
            log_fh.flush()
        return {
            "attempted": True,
            "passed": True,
            "returncode": 0,
            "results": results,
        }

    def _merge_branch_to_main(self, branch_name: str, task: PortalTask, attempt: int) -> dict[str, Any]:
        started_at = utc_now()
        dirty_overlap = self._dirty_merge_conflict_paths(branch_name)
        if dirty_overlap:
            result = {
                "attempted": True,
                "merged": False,
                "returncode": 2,
                "branch": branch_name,
                "started_at": started_at,
                "finished_at": utc_now(),
                "merge_commit": "",
                "stdout": "",
                "stderr": "",
                "reason": "main_checkout_dirty_conflict",
                "dirty_paths": dirty_overlap,
            }
            self._record_event("merge_finished", result)
            return result
        merge_lock = self._repo_merge_lock_path()
        lock_metadata = self._build_merge_lock_metadata(branch_name, task, attempt, started_at)
        lock_fd, lock_reason, existing_lock = self._try_acquire_lock(
            merge_lock,
            lock_kind="merge",
            owner_active=self._merge_lock_owner_is_active,
        )
        if lock_fd is None:
            result = {
                "attempted": False,
                "merged": False,
                "reason": lock_reason,
                "branch": branch_name,
                "started_at": started_at,
            }
            if existing_lock:
                result["lock_owner_pid"] = int(existing_lock.get("pid") or 0)
                result["lock_owner_branch"] = str(existing_lock.get("branch") or "")
            return result

        try:
            self._write_lock_metadata(lock_fd, lock_metadata)
            self._record_event(
                "merge_started",
                {"task_id": task.task_id, "attempt": attempt, "branch": branch_name, "started_at": started_at},
            )
            command = [
                "git",
                "merge",
                "--no-ff",
                "--no-edit",
                branch_name,
            ]
            merge = subprocess.run(
                command,
                cwd=self.repo_root,
                text=True,
                capture_output=True,
                check=False,
            )
            finished_at = utc_now()
            merge_commit = ""
            if merge.returncode == 0:
                merge_commit = self._run_git(["rev-parse", "HEAD"], cwd=self.repo_root).stdout.strip()
            result = {
                "attempted": True,
                "merged": merge.returncode == 0,
                "returncode": merge.returncode,
                "branch": branch_name,
                "command": command,
                "started_at": started_at,
                "finished_at": finished_at,
                "merge_commit": merge_commit,
                "stdout": merge.stdout[-4000:],
                "stderr": merge.stderr[-4000:],
            }
            self._record_event("merge_finished", result)
            return result
        finally:
            try:
                if merge_lock.exists():
                    merge_lock.unlink()
            except OSError:
                logger.warning("Failed to remove merge lock %s", merge_lock)

    def _cleanup_merged_worktree(self, worktree_path: Path | None, branch_name: str) -> dict[str, Any]:
        started_at = utc_now()
        removed_worktree = False
        deleted_branch = False
        errors: list[str] = []
        try:
            if worktree_path is not None and worktree_path.exists():
                self._run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=self.repo_root)
                removed_worktree = True
            if self._git_ref_exists(branch_name):
                self._run_git(["branch", "-D", branch_name], cwd=self.repo_root)
                deleted_branch = True
        except RuntimeError as exc:
            errors.append(str(exc))

        if errors:
            result = {
                "cleaned": False,
                "branch": branch_name,
                "worktree_path": str(worktree_path or ""),
                "started_at": started_at,
                "finished_at": utc_now(),
                "removed_worktree": removed_worktree,
                "deleted_branch": deleted_branch,
                "error": "\n".join(errors),
            }
            self._record_event("cleanup_finished", result)
            return result

        result = {
            "cleaned": True,
            "branch": branch_name,
            "worktree_path": str(worktree_path or ""),
            "started_at": started_at,
            "finished_at": utc_now(),
            "removed_worktree": removed_worktree,
            "deleted_branch": deleted_branch,
        }
        self._record_event("cleanup_finished", result)
        return result

    def _dirty_merge_conflict_paths(self, branch_name: str) -> list[str]:
        dirty_paths = self._dirty_worktree_paths(self.repo_root)
        if not dirty_paths:
            return []
        branch_paths = self._branch_changed_paths(branch_name)
        return sorted(dirty_paths & branch_paths)

    def _dirty_worktree_paths(self, cwd: Path) -> set[str]:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return set()
        paths: set[str] = set()
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            path_text = line[3:].strip()
            if " -> " in path_text:
                original, renamed = path_text.split(" -> ", 1)
                if original:
                    paths.add(original.strip())
                if renamed:
                    paths.add(renamed.strip())
                continue
            if path_text:
                paths.add(path_text)
        return paths

    def _branch_changed_paths(self, branch_name: str) -> set[str]:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"HEAD..{branch_name}"],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _reconcile_failed_merges(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for event in self._failed_merge_candidates():
            task_id = str(event.get("task_id") or "")
            attempt = int(event.get("attempt") or 0)
            branch = str(event.get("branch") or "")
            worktree_path_text = str(event.get("worktree_path") or "")
            worktree_path = Path(worktree_path_text) if worktree_path_text else None
            implementation_commit = str(event.get("implementation_commit") or "")
            if not task_id or not implementation_commit:
                continue
            if self._git_ref_is_ancestor(implementation_commit, "HEAD"):
                cleanup_result = self._cleanup_merged_worktree(worktree_path, branch) if branch else {}
                result = {
                    "task_id": task_id,
                    "attempt": attempt,
                    "branch": branch,
                    "implementation_commit": implementation_commit,
                    "resolved": True,
                    "reason": "implementation_commit_already_merged",
                    "cleanup_result": cleanup_result,
                }
                self._record_event("merge_reconciled", result)
                results.append(result)
                continue
            if not branch or not self._git_ref_exists(branch):
                result = {
                    "task_id": task_id,
                    "attempt": attempt,
                    "branch": branch,
                    "implementation_commit": implementation_commit,
                    "resolved": False,
                    "reason": "implementation_branch_missing",
                }
                self._record_event("merge_reconcile_skipped", result)
                results.append(result)
                continue

            task = PortalTask(
                task_id=task_id,
                title=str(event.get("title") or "failed implementation merge"),
                status="todo",
                completion="manual",
                priority="P2",
                track="ops",
            )
            merge_result = self._merge_branch_to_main(branch, task, attempt)
            cleanup_result = {}
            if merge_result.get("merged"):
                cleanup_result = self._cleanup_merged_worktree(worktree_path, branch)
            result = {
                "task_id": task_id,
                "attempt": attempt,
                "branch": branch,
                "implementation_commit": implementation_commit,
                "resolved": bool(merge_result.get("merged")),
                "reason": "merge_retried",
                "merge_result": merge_result,
                "cleanup_result": cleanup_result,
            }
            self._record_event("merge_reconciled", result)
            results.append(result)
        return results

    def _failed_merge_candidates(self) -> list[dict[str, Any]]:
        candidates: dict[tuple[str, str], dict[str, Any]] = {}
        reconciled_commits: set[str] = set()
        for event in self._iter_events():
            if str(event.get("type") or "") == "merge_reconciled" and event.get("resolved"):
                implementation_commit = str(event.get("implementation_commit") or "")
                if implementation_commit:
                    reconciled_commits.add(implementation_commit)
                continue
            if str(event.get("type") or "") != "implementation_finished":
                continue
            implementation_commit = str(event.get("implementation_commit") or "")
            if not implementation_commit or implementation_commit in reconciled_commits:
                continue
            validation = event.get("validation_result") or {}
            if isinstance(validation, dict) and validation.get("attempted") and not validation.get("passed", False):
                continue
            merge_result = event.get("merge_result") or {}
            if not isinstance(merge_result, dict):
                continue
            if not merge_result.get("attempted") or merge_result.get("merged"):
                continue
            task_id = str(event.get("task_id") or "")
            key = (task_id, implementation_commit)
            candidates[key] = event

        unresolved: list[dict[str, Any]] = []
        for event in candidates.values():
            implementation_commit = str(event.get("implementation_commit") or "")
            if implementation_commit in reconciled_commits:
                continue
            if implementation_commit and not self._git_ref_is_ancestor(implementation_commit, "HEAD"):
                unresolved.append(event)
                continue
            cleanup = event.get("cleanup_result") or {}
            if isinstance(cleanup, dict) and not cleanup.get("cleaned", False):
                unresolved.append(event)
        return unresolved

    def _unresolved_merge_failures_by_task(self) -> dict[str, dict[str, Any]]:
        failures: dict[str, dict[str, Any]] = {}
        for event in self._failed_merge_candidates():
            task_id = str(event.get("task_id") or "")
            implementation_commit = str(event.get("implementation_commit") or "")
            if task_id and implementation_commit and not self._git_ref_is_ancestor(implementation_commit, "HEAD"):
                failures[task_id] = event
        return failures

    def _has_unresolved_merge_failure(self, task: PortalTask, previous: PortalTaskState) -> bool:
        if previous.last_implementation_task_id != task.task_id:
            return False
        if not previous.last_implementation_commit:
            return False
        if previous.last_merge_returncode in (None, 0):
            return False
        if previous.last_merge_commit:
            return False
        return not self._git_ref_is_ancestor(previous.last_implementation_commit, "HEAD")

    def _git_ref_is_ancestor(self, ancestor: str, descendant: str) -> bool:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def _git_ref_exists(self, ref: str) -> bool:
        if not ref:
            return False
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def _implementation_lock_path(self) -> Path:
        return self.state_path.parent / "implementation.lock"

    def _build_implementation_lock_metadata(self, task: PortalTask, attempt: int, started_at: str) -> dict[str, Any]:
        return {
            "kind": "implementation",
            "pid": os.getpid(),
            "owner_script": Path(sys.argv[0]).name,
            "repo_root": str(self.repo_root.resolve()),
            "state_dir": str(self.state_path.parent.resolve()),
            "task_id": task.task_id,
            "attempt": attempt,
            "started_at": started_at,
        }

    def _build_merge_lock_metadata(
        self,
        branch_name: str,
        task: PortalTask,
        attempt: int,
        started_at: str,
    ) -> dict[str, Any]:
        return {
            "kind": "merge",
            "pid": os.getpid(),
            "owner_script": Path(sys.argv[0]).name,
            "repo_root": str(self.repo_root.resolve()),
            "task_id": task.task_id,
            "attempt": attempt,
            "branch": branch_name,
            "started_at": started_at,
        }

    def _implementation_lock_owner_is_active(self, metadata: dict[str, Any]) -> bool:
        state_dir = str(metadata.get("state_dir") or "")
        if state_dir and Path(state_dir).resolve() != self.state_path.parent.resolve():
            return False
        return self._lock_owner_is_active(metadata, expected_kind="implementation")

    def _merge_lock_owner_is_active(self, metadata: dict[str, Any]) -> bool:
        repo_root = str(metadata.get("repo_root") or "")
        if repo_root and Path(repo_root).resolve() != self.repo_root.resolve():
            return False
        return self._lock_owner_is_active(metadata, expected_kind="merge")

    def _lock_owner_is_active(self, metadata: dict[str, Any], *, expected_kind: str) -> bool:
        kind = str(metadata.get("kind") or "")
        if kind and kind != expected_kind:
            return False
        try:
            pid = int(metadata.get("pid") or 0)
        except (TypeError, ValueError):
            return False
        if not process_is_running(pid):
            return False
        owner_script = str(metadata.get("owner_script") or "")
        command_line = process_command_line(pid)
        if owner_script and owner_script not in command_line:
            return False
        return True

    def _try_acquire_lock(
        self,
        lock_path: Path,
        *,
        lock_kind: str,
        owner_active: Any,
    ) -> tuple[int | None, str, dict[str, Any] | None]:
        for _ in range(2):
            try:
                return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY), "acquired", None
            except FileExistsError:
                existing = load_json_dict(lock_path)
                if existing is not None and owner_active(existing):
                    return None, "lock_exists", existing
                if not self._clear_stale_lock(lock_path, lock_kind=lock_kind, metadata=existing):
                    return None, "lock_cleanup_failed", existing
        existing = load_json_dict(lock_path)
        if existing is not None and owner_active(existing):
            return None, "lock_exists", existing
        return None, "lock_unavailable", existing

    def _write_lock_metadata(self, lock_fd: int, metadata: dict[str, Any]) -> None:
        try:
            os.write(lock_fd, json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8"))
        finally:
            os.close(lock_fd)

    def _clear_stale_lock(self, lock_path: Path, *, lock_kind: str, metadata: dict[str, Any] | None) -> bool:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            logger.warning("Failed to remove stale %s lock %s", lock_kind, lock_path)
            return False
        self._record_event(
            f"{lock_kind}_lock_cleared",
            {
                "lock_path": str(lock_path),
                "lock_owner_pid": int(metadata.get("pid") or 0) if metadata else 0,
                "task_id": str(metadata.get("task_id") or "") if metadata else "",
                "branch": str(metadata.get("branch") or "") if metadata else "",
            },
        )
        return True

    def _find_live_inflight_implementation(self) -> dict[str, Any] | None:
        inflight_events = self._inflight_implementation_events()
        for event in reversed(inflight_events):
            if self._implementation_process_active(event):
                return event
        return None

    def _inflight_implementation_events(self) -> list[dict[str, Any]]:
        inflight: dict[tuple[str, int], dict[str, Any]] = {}
        for event in self._iter_events():
            event_type = str(event.get("type") or "")
            task_id = str(event.get("task_id") or "")
            attempt = int(event.get("attempt") or 0)
            if not task_id or attempt <= 0:
                continue
            key = (task_id, attempt)
            if event_type == "implementation_started":
                inflight[key] = event
            elif event_type == "implementation_finished":
                inflight.pop(key, None)

        return list(inflight.values())

    def _latest_implementation_finished_by_task(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for event in self._iter_events():
            if str(event.get("type") or "") != "implementation_finished":
                continue
            task_id = str(event.get("task_id") or "")
            if task_id:
                latest[task_id] = event
        return latest

    def _task_has_recent_no_change_outcome(
        self,
        task_id: str,
        latest_results: dict[str, dict[str, Any]],
        *,
        now_ts: float | None = None,
    ) -> bool:
        latest = latest_results.get(task_id)
        if not latest:
            return False
        commit_result = latest.get("commit_result") or {}
        if not isinstance(commit_result, dict):
            return False
        if commit_result.get("reason") != "no_changes":
            return False
        if int(latest.get("returncode") or 0) != 0:
            return False
        event_timestamp = parse_timestamp(str(latest.get("timestamp") or ""))
        if event_timestamp is None:
            return False
        age = (now_ts or time.time()) - event_timestamp.timestamp()
        return max(0.0, age) < RECENT_NO_CHANGE_COOLDOWN_SECONDS

    def _iter_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for raw_line in self.events_path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    def _implementation_process_active(self, event: dict[str, Any]) -> bool:
        worktree_path = str(event.get("worktree_path") or "")
        command = event.get("command") or []
        process_lines = self._list_process_commands()
        if worktree_path:
            return any(worktree_path in line for line in process_lines)
        if isinstance(command, list):
            command_text = " ".join(str(item) for item in command if item)
            if command_text:
                return any(command_text in line for line in process_lines)
        return False

    def _list_process_commands(self) -> list[str]:
        result = subprocess.run(
            ["ps", "-eo", "args="],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _repo_merge_lock_path(self) -> Path:
        git_common_dir = self._run_git(["rev-parse", "--git-common-dir"], cwd=self.repo_root).stdout.strip()
        path = Path(git_common_dir)
        if not path.is_absolute():
            path = self.repo_root / path
        return path / "implementation-main-merge.lock"

    def _run_git(self, args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result

    def _build_implementation_command(self, workspace_path: Path) -> list[str]:
        if self.implementation_command:
            return shlex.split(self.implementation_command)
        env_command = os.environ.get("IMPLEMENTATION_DAEMON_COMMAND", "").strip()
        if env_command:
            return shlex.split(env_command)
        codex = shutil.which("codex")
        if codex:
            return [codex, "exec", "--full-auto", "-C", str(workspace_path), "-"]
        raise RuntimeError(
            "No implementation command configured. Install codex or set IMPLEMENTATION_DAEMON_COMMAND."
        )

    def _build_implementation_prompt(self, task: PortalTask, attempt: int) -> str:
        return f"""You are an autonomous implementation agent working in this repository.

Implement exactly this backlog task and keep changes scoped.

Task:
- ID: {task.task_id}
- Title: {task.title}
- Priority: {task.priority}
- Track: {task.track}
- Attempt: {attempt}
- Todo file: {self.todo_path}
- Source line: {task.source_line}
- Depends on: {", ".join(task.depends_on) or "none"}
- Expected outputs: {", ".join(task.outputs) or "none listed"}
- Validation commands: {"; ".join(task.validation) or "none listed"}
- Acceptance: {task.acceptance or "none listed"}

Primary plan document:
- docs/AI_AGENT_CHAT_IMPLEMENTATION_PLAN.md when the task ID starts with AGENT-
- docs/211_SERVICE_NAVIGATION_PORTAL_PLAN.md when the task ID starts with PORTAL-

Rules:
- Read the relevant plan and nearby code before editing.
- Do not revert unrelated local changes.
- Prefer existing repo patterns and small, reviewable changes.
- Implement the expected outputs for this task.
- Run the listed validation commands when practical.
- The daemon will run the listed validation commands and will only commit and merge the worktree if they pass.
- Leave generated artifacts and shared dependency paths alone; the daemon restores dist, screenshot artifacts, and linked node_modules before commit.
- If validation cannot be run, record why in your final response.
- Do not mark the backlog task completed manually unless the task explicitly asks for TODO metadata changes.
- Final response should list changed files and validation results.
"""

    def _build_recommended_actions(self, task: PortalTask) -> list[str]:
        actions = [f"Implement outputs for {task.task_id}: {', '.join(task.outputs)}"]
        for command in task.validation:
            actions.append(f"Validate with: {command}")
        if task.acceptance:
            actions.append(f"Acceptance: {task.acceptance}")
        return actions

    def _select_next_task(
        self,
        tasks: list[PortalTask],
        resolved_statuses: dict[str, str],
        strategy: dict[str, Any],
        unresolved_merge_failures: dict[str, dict[str, Any]],
        recent_outcomes: dict[str, dict[str, Any]],
    ) -> PortalTask | None:
        ready = [task for task in tasks if resolved_statuses.get(task.task_id) == "ready"]
        if not ready:
            return None
        focus_order = {
            track: index
            for index, track in enumerate(
                [str(item).lower() for item in strategy.get("focus_tracks", DEFAULT_TRACKS)]
            )
        }
        deprioritized = {str(item) for item in strategy.get("deprioritized_tasks", [])}

        def sort_key(task: PortalTask) -> tuple[int, int, int, int, int, str]:
            selection_penalty = 0
            if task.task_id in unresolved_merge_failures:
                selection_penalty += UNRESOLVED_MERGE_SELECTION_PENALTY
            if self._task_has_recent_no_change_outcome(task.task_id, recent_outcomes):
                selection_penalty += NO_CHANGE_SELECTION_PENALTY
            return (
                selection_penalty,
                PRIORITY_ORDER.get(task.priority, 99),
                1 if task.task_id in deprioritized else 0,
                focus_order.get(task.track, len(focus_order)),
                len(task.depends_on),
                task.task_id,
            )

        return sorted(ready, key=sort_key)[0]

    def _record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        event = {"type": event_type, "timestamp": utc_now(), **payload}
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the portal implementation backlog daemon")
    parser.add_argument("--once", action="store_true", help="Run one backlog pass and exit")
    parser.add_argument("--interval", type=float, default=300.0, help="Seconds between backlog passes")
    parser.add_argument(
        "--todo-path",
        type=Path,
        default=Path("docs/211_SERVICE_NAVIGATION_PORTAL_TODO.md"),
        help="Machine-readable markdown backlog",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("data/portal_implementation/state"),
        help="Portal daemon state directory",
    )
    parser.add_argument(
        "--task-prefix",
        default=TASK_HEADER_PREFIX,
        help="Markdown heading prefix for tasks, for example '## PORTAL-' or '## AGENT-'",
    )
    parser.add_argument(
        "--state-prefix",
        default="portal",
        help="State file prefix inside --state-dir",
    )
    parser.add_argument("--implement", action="store_true", help="Invoke an autonomous implementation agent for the ready task")
    parser.add_argument(
        "--implementation-command",
        default="",
        help="Command used for implementation. Defaults to codex exec --full-auto.",
    )
    parser.add_argument("--implementation-timeout", type=float, default=DEFAULT_IMPLEMENTATION_TIMEOUT_SECONDS)
    parser.add_argument(
        "--no-ephemeral-worktree",
        action="store_true",
        help="Run the implementation command in the main checkout instead of an isolated temporary git worktree",
    )
    parser.add_argument(
        "--worktree-root",
        type=Path,
        default=None,
        help="Directory for temporary implementation worktrees. Defaults to the system temp directory.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    return parser.parse_args(argv)


TodoTask = PortalTask
TodoTaskState = PortalTaskState
TodoImplementationDaemon = PortalImplementationDaemon


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    daemon = PortalImplementationDaemon(
        todo_path=args.todo_path,
        state_path=args.state_dir / f"{args.state_prefix}_task_state.json",
        strategy_path=args.state_dir / f"{args.state_prefix}_strategy.json",
        events_path=args.state_dir / f"{args.state_prefix}_events.jsonl",
        repo_root=REPO_ROOT,
        task_header_prefix=args.task_prefix,
        implement=args.implement,
        implementation_command=args.implementation_command or None,
        implementation_timeout=args.implementation_timeout,
        use_ephemeral_worktree=args.implement and not args.no_ephemeral_worktree,
        worktree_root=args.worktree_root,
    )
    while True:
        result = daemon.run_once()
        logger.info("Portal implementation daemon pass complete: %s", result)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
