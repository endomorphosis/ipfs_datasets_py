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
DEFAULT_TRACKS = [
    "platform",
    "agent",
    "graphrag",
    "data",
    "ui",
    "mobile",
    "wallet",
    "privacy",
    "runtime",
    "quality",
    "collab",
    "pwa",
    "ops",
]
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DEFAULT_IMPLEMENTATION_TIMEOUT_SECONDS = 7200.0
RECENT_NO_CHANGE_COOLDOWN_SECONDS = 1800.0
NO_CHANGE_SELECTION_PENALTY = 50
UNRESOLVED_MERGE_SELECTION_PENALTY = 1000
DEFAULT_IMPLEMENTATION_PLAYWRIGHT_PORT_BASE = 5300
IMPLEMENTATION_PLAYWRIGHT_ATTEMPT_SLOTS = 10
IMPLEMENTATION_PLAYWRIGHT_FAMILY_OFFSETS = {
    "agent_chat": 0,
    "portal": 100,
    "wallet": 200,
    "worldid": 300,
    "worldid_ui": 300,
    "worldid_backend": 400,
    "clzkml": 500,
    "provekit": 600,
    "portland_graphrag": 700,
}
SHARED_WORKTREE_PATHS = ("wallet_interface/ui/node_modules",)
WORKTREE_SUBMODULE_PATHS = ("hallucinate_app", "ipfs_datasets_py", "swissknife")
EPHEMERAL_WORKTREE_PATHS = (
    *SHARED_WORKTREE_PATHS,
    ".pytest_cache",
    "test-results",
    "wallet_interface/__pycache__",
    "wallet_interface/ui/dist",
    "wallet_interface/ui/playwright-report",
    "wallet_interface/ui/test-results",
    "wallet_interface/ui/artifacts/ui-iterations/latest",
    "wallet_interface/ui/artifacts/ui-review",
    "wallet_interface/ui/artifacts/ui-screenshots",
    "wallet_interface/ui/artifacts/ui-screenshots/latest",
)
GENERATED_WORKTREE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "playwright-report",
    "test-results",
}
GENERATED_WORKTREE_SUFFIXES = (".pyc", ".pyo")
UNTRACKED_WORKTREE_CONTEXT_PREFIXES = (
    ".gitmodules",
    "docs/",
    "implementation_plan/",
    "scripts/",
    "scraper/",
    "tests/",
    "wallet_interface/",
)
GENERATED_ADD_ADD_CONFLICT_PREFIXES = (
    "data/",
    "docs/",
    "implementation_plan/",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copilot_fallback_command(*, codex: str | None, copilot: str, workspace_path: Path) -> list[str]:
        return [
                "bash",
                "-lc",
                """
prompt_file=$(mktemp)
trap 'rm -f "$prompt_file"' EXIT
cat > "$prompt_file"
codex_bin="$1"
copilot_bin="$2"
workspace="$3"
if [[ -n "$codex_bin" ]]; then
    if "$codex_bin" exec --dangerously-bypass-approvals-and-sandbox -C "$workspace" - < "$prompt_file"; then
        exit 0
    else
        rc=$?
        printf 'codex exec failed with exit %s; falling back to copilot\n' "$rc" >&2
    fi
fi
exec "$copilot_bin" --silent --allow-all-tools --allow-all-paths --no-ask-user --autopilot --prompt "$(cat "$prompt_file")"
""",
                "bash",
                codex or "",
                copilot,
                str(workspace_path),
        ]


def split_csv(value: str) -> list[str]:
    raw = [item.strip() for item in value.split(",")]
    return [item for item in raw if item and item.lower() not in {"none", "n/a"}]


def normalize_scope_items(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not values:
        return ()
    normalized: list[str] = []
    for value in values:
        for item in str(value).split(","):
            stripped = item.strip().lower()
            if stripped:
                normalized.append(stripped)
    return tuple(dict.fromkeys(normalized))


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
    active_attempt: int = 0
    active_phase: str = ""
    active_phase_started_at: str = ""
    active_phase_detail: str = ""
    active_log_path: str = ""
    active_worktree_path: str = ""
    active_branch: str = ""
    implementation_in_progress: bool = False
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
            active_attempt=int(payload.get("active_attempt") or 0),
            active_phase=str(payload.get("active_phase") or ""),
            active_phase_started_at=str(payload.get("active_phase_started_at") or ""),
            active_phase_detail=str(payload.get("active_phase_detail") or ""),
            active_log_path=str(payload.get("active_log_path") or ""),
            active_worktree_path=str(payload.get("active_worktree_path") or ""),
            active_branch=str(payload.get("active_branch") or ""),
            implementation_in_progress=bool(payload.get("implementation_in_progress")),
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
        allowed_tracks: list[str] | tuple[str, ...] | None = None,
        allowed_task_ids: list[str] | tuple[str, ...] | None = None,
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
        self.allowed_tracks = normalize_scope_items(allowed_tracks)
        self.allowed_task_ids = normalize_scope_items(allowed_task_ids)

    def _implementation_family_key(self) -> str:
        state_name = self.state_path.name
        for suffix in ("_task_state.json", "_state.json", ".json"):
            if state_name.endswith(suffix):
                return state_name[: -len(suffix)] or self.state_path.stem
        return self.state_path.stem

    @staticmethod
    def _stable_slot(value: str, modulo: int) -> int:
        if modulo <= 1:
            return 0
        total = sum((index + 1) * ord(character) for index, character in enumerate(value))
        return total % modulo

    def _implementation_playwright_port_base(self) -> int:
        raw = os.environ.get("IMPLEMENTATION_PLAYWRIGHT_PORT_BASE", "").strip()
        if not raw:
            return DEFAULT_IMPLEMENTATION_PLAYWRIGHT_PORT_BASE
        try:
            port = int(raw)
        except ValueError:
            logger.warning("Ignoring invalid IMPLEMENTATION_PLAYWRIGHT_PORT_BASE=%r", raw)
            return DEFAULT_IMPLEMENTATION_PLAYWRIGHT_PORT_BASE
        if port < 1024 or port > 65000:
            logger.warning("Ignoring out-of-range IMPLEMENTATION_PLAYWRIGHT_PORT_BASE=%r", raw)
            return DEFAULT_IMPLEMENTATION_PLAYWRIGHT_PORT_BASE
        return port

    def _implementation_playwright_port(self, task: PortalTask, attempt: int) -> str:
        override = os.environ.get("IMPLEMENTATION_DAEMON_PLAYWRIGHT_PORT", "").strip()
        if override:
            return override

        family_key = self._implementation_family_key()
        family_offset = IMPLEMENTATION_PLAYWRIGHT_FAMILY_OFFSETS.get(family_key)
        if family_offset is None:
            family_offset = 1000 + (self._stable_slot(family_key, 40) * 100)
        task_slot = self._stable_slot(task.task_id, 10) * IMPLEMENTATION_PLAYWRIGHT_ATTEMPT_SLOTS
        attempt_slot = max(attempt - 1, 0) % IMPLEMENTATION_PLAYWRIGHT_ATTEMPT_SLOTS
        return str(self._implementation_playwright_port_base() + family_offset + task_slot + attempt_slot)

    def _build_implementation_environment(self, task: PortalTask, attempt: int) -> dict[str, str]:
        env = os.environ.copy()
        playwright_port = self._implementation_playwright_port(task, attempt)
        env["PLAYWRIGHT_PORT"] = playwright_port
        env["IMPLEMENTATION_PLAYWRIGHT_PORT"] = playwright_port
        return env

    def _task_in_scope(self, task: PortalTask) -> bool:
        if not self.allowed_tracks and not self.allowed_task_ids:
            return True
        return task.track.lower() in self.allowed_tracks or task.task_id.lower() in self.allowed_task_ids

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
        scoped_tasks = [task for task in tasks if self._task_in_scope(task)]
        if not scoped_tasks:
            scope_detail = []
            if self.allowed_tracks:
                scope_detail.append(f"tracks={','.join(self.allowed_tracks)}")
            if self.allowed_task_ids:
                scope_detail.append(f"task_ids={','.join(self.allowed_task_ids)}")
            raise RuntimeError(f"No in-scope tasks found in {self.todo_path}: {'; '.join(scope_detail)}")
        scoped_task_ids = {task.task_id for task in scoped_tasks}
        previous = PortalTaskState.load(self.state_path)
        strategy = self.load_strategy()
        now = utc_now()
        status_completed_task_ids = {task.task_id for task in tasks if task.status == "completed"}
        strategy_blocked_task_ids = {str(task_id) for task_id in strategy.get("blocked_tasks", [])}
        merge_skip_task_ids = status_completed_task_ids | strategy_blocked_task_ids
        merge_reconciliation = self._reconcile_failed_merges(skip_task_ids=merge_skip_task_ids)
        unresolved_merge_failures = self._unresolved_merge_failures_by_task(skip_task_ids=merge_skip_task_ids)
        recent_outcomes = self._latest_implementation_finished_by_task()
        successfully_merged_task_ids = self._successfully_merged_task_ids()
        live_inflight_implementation = self._find_live_inflight_implementation()

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
            merged_complete = task.task_id in successfully_merged_task_ids and not unresolved_merge_failure
            if task.status == "completed" or artifact_complete or merged_complete:
                completed_set.add(task.task_id)

        for task in tasks:
            if task.task_id in completed_set:
                resolved_statuses[task.task_id] = "completed"
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

        selected = self._select_next_task(
            scoped_tasks,
            resolved_statuses,
            strategy,
            unresolved_merge_failures,
            recent_outcomes,
        )
        scoped_completed_set = completed_set & scoped_task_ids
        state = PortalTaskState.load(self.state_path)
        state.heartbeat_at = now
        newly_completed = [task_id for task_id in newly_completed if task_id in scoped_task_ids]
        if newly_completed or not state.last_progress_at:
            state.last_progress_at = now
        state.completed_task_ids = sorted(scoped_completed_set)
        state.completed_count = len(state.completed_task_ids)
        state.ready_task_ids = [task.task_id for task in scoped_tasks if resolved_statuses[task.task_id] == "ready"]
        state.waiting_task_ids = [task.task_id for task in scoped_tasks if resolved_statuses[task.task_id] == "waiting"]
        state.blocked_task_ids = [task.task_id for task in scoped_tasks if resolved_statuses[task.task_id] == "blocked"]
        state.ready_count = len(state.ready_task_ids)
        state.waiting_count = len(state.waiting_task_ids)
        state.blocked_count = len(state.blocked_task_ids)
        state.task_count = len(scoped_tasks)
        state.task_statuses = {task.task_id: resolved_statuses[task.task_id] for task in scoped_tasks}
        state.task_artifacts = {task.task_id: task_artifacts[task.task_id] for task in scoped_tasks}
        state.task_validation = {task.task_id: task.validation for task in scoped_tasks if task.validation}
        state.strategy_generation = int(strategy.get("generation", 0))
        state.implementation_attempts = previous.implementation_attempts
        state.active_attempt = previous.active_attempt
        state.active_phase = previous.active_phase
        state.active_phase_started_at = previous.active_phase_started_at
        state.active_phase_detail = previous.active_phase_detail
        state.active_log_path = previous.active_log_path
        state.active_worktree_path = previous.active_worktree_path
        state.active_branch = previous.active_branch
        state.implementation_in_progress = previous.implementation_in_progress
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
        if previous.implementation_in_progress and live_inflight_implementation is None:
            self._clear_active_execution_state(state)
            self._record_event(
                "implementation_state_recovered",
                {
                    "task_id": previous.active_task_id or previous.last_implementation_task_id,
                    "attempt": previous.active_attempt,
                    "reason": "inflight_process_missing",
                    "worktree_path": previous.active_worktree_path,
                    "branch": previous.active_branch,
                },
            )

        if selected is not None:
            if state.active_task_id != selected.task_id:
                state.active_task_started_at = now
                state.last_progress_at = now
                self._clear_active_execution_state(state)
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
            self._clear_active_execution_state(state)
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
        implementation_env = self._build_implementation_environment(task, attempt)
        playwright_port = implementation_env["PLAYWRIGHT_PORT"]
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
        todo_update_result: dict[str, Any] = {}

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
                    environment=implementation_env,
                )
            self.implementation_log_dir.mkdir(parents=True, exist_ok=True)
            self._mark_implementation_started(
                state,
                task=task,
                attempt=attempt,
                started_at=started_at,
                log_path=log_path,
            )
            self._record_event(
                "implementation_started",
                {
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "command": command,
                    "log_path": str(log_path),
                    "playwright_port": playwright_port,
                },
            )
            with log_path.open("w", encoding="utf-8") as log_fh:
                log_fh.write(f"Task: {task.task_id} {task.title}\n")
                log_fh.write(f"Started: {started_at}\n")
                log_fh.write(f"Command: {' '.join(shlex.quote(item) for item in command)}\n\n")
                log_fh.write(f"Environment: PLAYWRIGHT_PORT={playwright_port}\n\n")
                log_fh.flush()
                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    cwd=workspace_path,
                    env=implementation_env,
                    timeout=self.implementation_timeout,
                    check=False,
                )
            effective_returncode = completed.returncode
            if completed.returncode == 0:
                self._mark_active_phase(
                    state,
                    phase="validating",
                    phase_detail="; ".join(task.validation) if task.validation else "",
                )
                validation_result = self._run_validation_commands(
                    workspace_path,
                    task,
                    log_path,
                    env=implementation_env,
                )
                if not validation_result.get("passed", False):
                    effective_returncode = int(validation_result.get("returncode") or 1)
            if effective_returncode == 0:
                todo_update_result = self._mark_task_completed_in_todo(task.task_id)
            finished_at = utc_now()
            state.implementation_attempts[task.task_id] = attempt
            state.last_implementation_task_id = task.task_id
            state.last_implementation_started_at = started_at
            state.last_implementation_finished_at = finished_at
            state.last_implementation_returncode = effective_returncode
            state.last_implementation_log_path = str(log_path)
            self._mark_implementation_finished(state, finished_at=finished_at)
            state.save(self.state_path)
            result = {
                "task_id": task.task_id,
                "attempt": attempt,
                "returncode": effective_returncode,
                "log_path": str(log_path),
                "playwright_port": playwright_port,
                "validation_result": validation_result,
            }
            if todo_update_result:
                result["todo_update_result"] = todo_update_result
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
            self._mark_implementation_finished(state, finished_at=finished_at)
            state.save(self.state_path)
            result = {
                "task_id": task.task_id,
                "attempt": attempt,
                "returncode": 124,
                "log_path": str(log_path),
                "playwright_port": playwright_port,
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

    def _mark_task_completed_in_todo(self, task_id: str) -> dict[str, Any]:
        todo_path = self.todo_path
        try:
            lines = todo_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError as exc:
            result = {"updated": False, "task_id": task_id, "reason": "read_failed", "error": str(exc)}
            self._record_event("todo_status_update_failed", result)
            return result

        heading = f"## {task_id}"
        in_task = False
        status_index: int | None = None
        for index, line in enumerate(lines):
            if line.startswith(self.task_header_prefix):
                if in_task:
                    break
                in_task = line.startswith(heading)
                continue
            if in_task and line.startswith("- Status:"):
                status_index = index
                break

        if status_index is None:
            result = {"updated": False, "task_id": task_id, "reason": "status_line_missing"}
            self._record_event("todo_status_update_failed", result)
            return result

        current = lines[status_index].split(":", 1)[1].strip()
        if normalize_status(current) == "completed":
            return {"updated": False, "task_id": task_id, "reason": "already_completed"}

        newline = "\n" if lines[status_index].endswith("\n") else ""
        lines[status_index] = "- Status: completed" + newline
        tmp_path = todo_path.with_name(f".{todo_path.name}.tmp")
        try:
            tmp_path.write_text("".join(lines), encoding="utf-8")
            os.replace(tmp_path, todo_path)
        except OSError as exc:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            result = {"updated": False, "task_id": task_id, "reason": "write_failed", "error": str(exc)}
            self._record_event("todo_status_update_failed", result)
            return result

        commit_result = self._commit_generated_file_update(
            todo_path,
            task_id=task_id,
            subject=f"{task_id}: mark todo completed",
        )
        result = {"updated": True, "task_id": task_id, "path": str(todo_path)}
        if commit_result:
            result["commit_result"] = commit_result
        self._record_event("todo_status_updated", result)
        return result

    def _commit_generated_file_update(self, path: Path, *, task_id: str, subject: str) -> dict[str, Any]:
        """Commit a daemon-owned generated file and any parent gitlink updates."""

        repo = self._git_toplevel_for_path(path.parent)
        if repo is None:
            return {"committed": False, "reason": "not_in_git_repo", "path": str(path)}
        relative = self._relative_to_repo(repo, path)
        if not relative:
            return {"committed": False, "reason": "path_outside_repo", "path": str(path), "repo": str(repo)}

        result = self._commit_specific_path(repo, relative, subject=subject)
        parent_results: list[dict[str, Any]] = []
        if result.get("committed"):
            parent_results = self._commit_parent_gitlink_updates(repo, task_id=task_id)
        if parent_results:
            result["parent_gitlink_commits"] = parent_results
        return result

    def _commit_parent_gitlink_updates(self, child_repo: Path, *, task_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        current = child_repo.resolve()
        repo_root = self.repo_root.resolve()
        while current != repo_root:
            parent = self._parent_git_toplevel_for_repo(current)
            if parent is None:
                break
            relative = self._relative_to_repo(parent, current)
            if not relative:
                break
            result = self._commit_specific_path(
                parent,
                relative,
                subject=f"{task_id}: update generated submodule pointer",
            )
            results.append(result)
            current = parent.resolve()
        return results

    def _commit_specific_path(self, repo: Path, relative: str, *, subject: str) -> dict[str, Any]:
        if not self._repo_relative_path_safe(relative):
            return {"committed": False, "reason": "unsafe_path", "repo": str(repo), "path": relative}
        unmerged = self._unmerged_worktree_paths(repo)
        if unmerged and relative not in unmerged:
            return {
                "committed": False,
                "reason": "repo_has_unrelated_unmerged_paths",
                "repo": str(repo),
                "path": relative,
                "unmerged_paths": sorted(unmerged),
            }
        status = self._path_status(repo, relative)
        if not status:
            return {"committed": False, "reason": "no_changes", "repo": str(repo), "path": relative}
        add = subprocess.run(
            ["git", "add", "--", relative],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if add.returncode != 0:
            return {
                "committed": False,
                "reason": "git_add_failed",
                "repo": str(repo),
                "path": relative,
                "returncode": add.returncode,
                "stdout": add.stdout[-4000:],
                "stderr": add.stderr[-4000:],
            }
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", relative],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if staged.returncode == 0:
            return {"committed": False, "reason": "no_staged_changes", "repo": str(repo), "path": relative}
        commit = subprocess.run(
            [
                "git",
                "-c",
                "user.name=Implementation Daemon",
                "-c",
                "user.email=implementation-daemon@example.invalid",
                "commit",
                "-m",
                subject,
                "--",
                relative,
            ],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if commit.returncode != 0:
            return {
                "committed": False,
                "reason": "git_commit_failed",
                "repo": str(repo),
                "path": relative,
                "returncode": commit.returncode,
                "stdout": commit.stdout[-4000:],
                "stderr": commit.stderr[-4000:],
            }
        commit_ref = self._run_git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
        return {
            "committed": True,
            "repo": str(repo),
            "path": relative,
            "commit": commit_ref,
            "status": status,
        }

    def _git_toplevel_for_path(self, cwd: Path) -> Path | None:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return Path(result.stdout.strip()).resolve()

    def _parent_git_toplevel_for_repo(self, repo: Path) -> Path | None:
        parent_dir = repo.resolve().parent
        parent = self._git_toplevel_for_path(parent_dir)
        if parent is None or parent.resolve() == repo.resolve():
            return None
        try:
            repo.resolve().relative_to(parent.resolve())
        except ValueError:
            return None
        return parent

    @staticmethod
    def _relative_to_repo(repo: Path, path: Path) -> str:
        try:
            return path.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            return ""

    def _path_status(self, repo: Path, relative: str) -> str:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", relative],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _unmerged_worktree_paths(self, repo: Path) -> set[str]:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _run_implementation_in_ephemeral_worktree(
        self,
        *,
        task: PortalTask,
        state: PortalTaskState,
        attempt: int,
        started_at: str,
        log_path: Path,
        prompt: str,
        environment: dict[str, str],
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
        playwright_port = environment["PLAYWRIGHT_PORT"]
        returncode = 1
        commit_result: dict[str, Any] = {"committed": False}
        failed_preservation_result: dict[str, Any] = {}
        todo_update_result: dict[str, Any] = {}

        try:
            baseline_ref = self._create_seeded_worktree(worktree_path, branch_name, task=task)
            command = self._build_implementation_command(worktree_path)
            self._mark_implementation_started(
                state,
                task=task,
                attempt=attempt,
                started_at=started_at,
                log_path=log_path,
                worktree_path=worktree_path,
                branch_name=branch_name,
            )
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
                    "playwright_port": playwright_port,
                },
            )
            with log_path.open("w", encoding="utf-8") as log_fh:
                log_fh.write(f"Task: {task.task_id} {task.title}\n")
                log_fh.write(f"Started: {started_at}\n")
                log_fh.write(f"Workspace: {worktree_path}\n")
                log_fh.write(f"Branch: {branch_name}\n")
                log_fh.write(f"Baseline: {baseline_ref}\n")
                log_fh.write(f"Command: {' '.join(shlex.quote(item) for item in command)}\n\n")
                log_fh.write(f"Environment: PLAYWRIGHT_PORT={playwright_port}\n\n")
                log_fh.flush()
                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    cwd=worktree_path,
                    env=environment,
                    timeout=self.implementation_timeout,
                    check=False,
            )
            returncode = completed.returncode
            if returncode == 0:
                self._mark_active_phase(
                    state,
                    phase="validating",
                    phase_detail="; ".join(task.validation) if task.validation else "",
                    worktree_path=worktree_path,
                    branch_name=branch_name,
                )
                self._prepare_worktree_for_validation(worktree_path, task=task, branch_name=branch_name)
                validation_result = self._run_validation_commands(
                    worktree_path,
                    task,
                    log_path,
                    env=environment,
                )
                if validation_result.get("passed", False):
                    commit_result = self._commit_worktree_changes(worktree_path, task, attempt)
                    implementation_commit = str(commit_result.get("commit", ""))
                    if implementation_commit:
                        self._mark_active_phase(
                            state,
                            phase="merging",
                            phase_detail=branch_name,
                            worktree_path=worktree_path,
                            branch_name=branch_name,
                        )
                        merge_result = self._merge_branch_to_main(
                            branch_name,
                            task,
                            attempt,
                            baseline_ref=baseline_ref,
                        )
                        if merge_result.get("merged"):
                            cleanup_result = self._cleanup_merged_worktree(worktree_path, branch_name)
                        else:
                            returncode = int(merge_result.get("returncode") or 1)
                    elif commit_result.get("reason") == "no_changes":
                        cleanup_result = self._cleanup_merged_worktree(worktree_path, branch_name)
                else:
                    returncode = int(validation_result.get("returncode") or 1)
                    failed_preservation_result = self._preserve_failed_validation_worktree(
                        worktree_path,
                        branch_name,
                        task,
                        attempt,
                        validation_result,
                    )
                    cleanup_result = dict(failed_preservation_result.get("cleanup_result") or cleanup_result)
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
        if returncode == 0:
            todo_update_result = self._mark_task_completed_in_todo(task.task_id)
        self._mark_implementation_finished(state, finished_at=finished_at)
        state.save(self.state_path)
        result = {
            "task_id": task.task_id,
            "attempt": attempt,
            "returncode": returncode,
            "log_path": str(log_path),
            "playwright_port": playwright_port,
            "worktree_path": str(worktree_path),
            "branch": branch_name,
            "baseline_ref": baseline_ref,
            "commit_result": commit_result,
            "implementation_commit": implementation_commit,
            "merge_result": merge_result,
            "validation_result": validation_result,
            "cleanup_result": cleanup_result,
            "failed_preservation_result": failed_preservation_result,
        }
        if todo_update_result:
            result["todo_update_result"] = todo_update_result
        self._record_event("implementation_finished", result)
        return result

    def _clear_active_execution_state(self, state: PortalTaskState) -> None:
        state.active_attempt = 0
        state.active_phase = ""
        state.active_phase_started_at = ""
        state.active_phase_detail = ""
        state.active_log_path = ""
        state.active_worktree_path = ""
        state.active_branch = ""
        state.implementation_in_progress = False

    def _mark_implementation_started(
        self,
        state: PortalTaskState,
        *,
        task: PortalTask,
        attempt: int,
        started_at: str,
        log_path: Path,
        worktree_path: Path | None = None,
        branch_name: str = "",
    ) -> None:
        state.active_task_id = task.task_id
        state.active_task_title = task.title
        state.active_task_track = task.track
        if not state.active_task_started_at:
            state.active_task_started_at = started_at
        state.active_attempt = attempt
        state.active_phase = "implementing"
        state.active_phase_started_at = started_at
        state.active_phase_detail = ""
        state.active_log_path = str(log_path)
        state.active_worktree_path = str(worktree_path) if worktree_path is not None else ""
        state.active_branch = branch_name
        state.implementation_in_progress = True
        state.last_implementation_task_id = task.task_id
        state.last_implementation_started_at = started_at
        state.last_implementation_finished_at = ""
        state.last_implementation_returncode = None
        state.last_implementation_log_path = str(log_path)
        state.last_implementation_worktree_path = str(worktree_path) if worktree_path is not None else ""
        state.last_implementation_branch = branch_name
        state.last_implementation_commit = ""
        state.heartbeat_at = started_at
        state.last_progress_at = started_at
        state.save(self.state_path)

    def _mark_active_phase(
        self,
        state: PortalTaskState,
        *,
        phase: str,
        phase_detail: str = "",
        worktree_path: Path | None = None,
        branch_name: str | None = None,
        at: str | None = None,
    ) -> None:
        timestamp = at or utc_now()
        if state.active_phase != phase:
            state.active_phase_started_at = timestamp
        elif not state.active_phase_started_at:
            state.active_phase_started_at = timestamp
        state.active_phase = phase
        state.active_phase_detail = phase_detail
        if worktree_path is not None:
            state.active_worktree_path = str(worktree_path)
        if branch_name is not None:
            state.active_branch = branch_name
        state.implementation_in_progress = True
        state.heartbeat_at = timestamp
        state.last_progress_at = timestamp
        state.save(self.state_path)

    def _mark_implementation_finished(self, state: PortalTaskState, *, finished_at: str) -> None:
        state.implementation_in_progress = False
        state.heartbeat_at = finished_at
        state.last_progress_at = finished_at
        self._clear_active_execution_state(state)

    def _create_seeded_worktree(
        self,
        worktree_path: Path,
        branch_name: str,
        *,
        task: PortalTask | None = None,
    ) -> str:
        self._run_git(
            ["worktree", "add", "-b", branch_name, str(worktree_path), self._main_branch_name()],
            cwd=self.repo_root,
        )
        baseline_ref = self._run_git(["rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()
        self._initialize_worktree_submodules(worktree_path, branch_name=branch_name)
        self._link_shared_worktree_paths(worktree_path)
        self._seed_untracked_worktree_context(worktree_path, task=task, overwrite_existing=True)
        return baseline_ref

    def _initialize_worktree_submodules(self, worktree_path: Path, *, branch_name: str = "") -> None:
        for relative in WORKTREE_SUBMODULE_PATHS:
            if self._create_local_submodule_worktree(worktree_path, relative, branch_name=branch_name):
                target = worktree_path / relative
                if self._is_git_worktree(target):
                    self._initialize_nested_worktree_submodules(
                        target,
                        branch_name=branch_name,
                        parent_relative=relative,
                    )
                continue
            if self._worktree_declares_submodule(worktree_path, relative):
                self._run_git(["submodule", "update", "--init", "--recursive", "--", relative], cwd=worktree_path)
                target = worktree_path / relative
                if self._is_git_worktree(target):
                    self._initialize_nested_worktree_submodules(
                        target,
                        branch_name=branch_name,
                        parent_relative=relative,
                    )

    def _initialize_nested_worktree_submodules(
        self,
        worktree_path: Path,
        *,
        branch_name: str,
        parent_relative: str,
    ) -> None:
        for relative in self._declared_submodule_paths(worktree_path):
            full_relative = f"{parent_relative.rstrip('/')}/{relative}"
            if self._create_local_submodule_worktree(
                worktree_path,
                relative,
                branch_name=branch_name,
                source_relative=full_relative,
            ):
                target = worktree_path / relative
                if self._is_git_worktree(target):
                    self._initialize_nested_worktree_submodules(
                        target,
                        branch_name=branch_name,
                        parent_relative=full_relative,
                    )
                continue

    def _create_local_submodule_worktree(
        self,
        worktree_path: Path,
        relative: str,
        *,
        branch_name: str = "",
        source_relative: str | None = None,
    ) -> bool:
        source_key = source_relative or relative
        source = (self.repo_root / source_key).resolve()
        if not source.exists() or not self._is_git_worktree(source):
            return False
        base_ref = self._submodule_gitlink_ref(worktree_path, relative) or "HEAD"
        target = worktree_path / relative
        if self._is_git_worktree(target) and not target.is_symlink():
            if branch_name:
                expected_branch = self._submodule_worktree_branch_name(branch_name, source_key)
                current_branch = self._git_current_branch(target)
                if current_branch and current_branch != expected_branch:
                    return False
            return True
        if target.exists() or target.is_symlink():
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        if branch_name:
            submodule_branch = self._submodule_worktree_branch_name(branch_name, source_key)
            if self._git_ref_exists_in_repo(source, submodule_branch):
                self._run_git(["worktree", "add", str(target), submodule_branch], cwd=source)
                return True
            self._run_git(["worktree", "add", "-b", submodule_branch, str(target), base_ref], cwd=source)
            return True
        self._run_git(["worktree", "add", "--detach", str(target), base_ref], cwd=source)
        return True

    def _submodule_gitlink_ref(self, worktree_path: Path, relative: str) -> str:
        if not self._repo_relative_path_safe(relative):
            return ""
        result = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            cwd=worktree_path,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    @staticmethod
    def _submodule_worktree_branch_name(branch_name: str, relative: str) -> str:
        safe_relative = relative.strip("/").replace("/", "-")
        return f"{branch_name}-submodule-{safe_relative}"

    def _is_git_worktree(self, path: Path) -> bool:
        if not path.exists() or path.is_symlink():
            return False
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        try:
            return Path(result.stdout.strip()).resolve() == path.resolve()
        except OSError:
            return False

    def _git_current_branch(self, cwd: Path) -> str:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _git_ref_exists_in_repo(self, cwd: Path, ref: str) -> bool:
        if not ref:
            return False
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def _worktree_declares_submodule(self, worktree_path: Path, relative: str) -> bool:
        return relative in self._declared_submodule_paths(worktree_path)

    def _declared_submodule_paths(self, worktree_path: Path) -> list[str]:
        gitmodules = worktree_path / ".gitmodules"
        if not gitmodules.exists():
            return []
        result = subprocess.run(
            ["git", "config", "--file", str(gitmodules), "--get-regexp", r"^submodule\..*\.path$"],
            cwd=worktree_path,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        paths: list[str] = []
        for line in result.stdout.splitlines():
            path = line.split(maxsplit=1)[-1].strip()
            if path and self._repo_relative_path_safe(path):
                paths.append(path)
        return paths

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

    def _prepare_worktree_for_validation(
        self,
        worktree_path: Path,
        *,
        task: PortalTask | None = None,
        branch_name: str = "",
    ) -> None:
        self._initialize_worktree_submodules(worktree_path, branch_name=branch_name)
        self._link_shared_worktree_paths(worktree_path)
        self._seed_untracked_worktree_context(worktree_path, task=task)

    def _seed_untracked_worktree_context(
        self,
        worktree_path: Path,
        *,
        task: PortalTask | None = None,
        overwrite_existing: bool = False,
    ) -> list[str]:
        """Copy relevant untracked source context into an ephemeral worktree."""

        seeded: list[str] = []
        for relative in self._untracked_worktree_context_paths():
            if not self._untracked_context_path_allowed(relative):
                continue
            source = self.repo_root / relative
            if not source.exists() or source.is_dir():
                continue
            target = worktree_path / relative
            if target.exists() or target.is_symlink():
                if not overwrite_existing:
                    continue
                if target.is_dir():
                    continue
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                target.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, target)
            seeded.append(relative)

        if seeded:
            payload: dict[str, Any] = {
                "worktree_path": str(worktree_path),
                "seeded_paths": seeded,
                "seeded_count": len(seeded),
            }
            if task is not None:
                payload["task_id"] = task.task_id
            self._record_event("worktree_context_seeded", payload)
        return seeded

    def _untracked_worktree_context_paths(self) -> list[str]:
        candidates: set[str] = set()
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=self.repo_root,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        paths = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
        candidates.update(path for path in paths if path)
        return sorted(candidates)

    def _untracked_context_path_allowed(self, relative: str) -> bool:
        if not relative or relative.startswith("/") or "\0" in relative:
            return False
        if ".." in Path(relative).parts:
            return False
        if any(self._path_matches_prefix(relative, prefix) for prefix in EPHEMERAL_WORKTREE_PATHS):
            return False
        if any(self._path_matches_prefix(relative, prefix) for prefix in WORKTREE_SUBMODULE_PATHS):
            return False
        return any(self._path_matches_prefix(relative, prefix) for prefix in UNTRACKED_WORKTREE_CONTEXT_PREFIXES)

    @staticmethod
    def _path_matches_prefix(relative: str, prefix: str) -> bool:
        normalized = prefix.rstrip("/")
        return relative == normalized or relative.startswith(f"{normalized}/")

    def _commit_worktree_changes(self, worktree_path: Path, task: PortalTask, attempt: int) -> dict[str, Any]:
        submodule_results = self._commit_worktree_submodule_changes(worktree_path, task, attempt)
        self._restore_ephemeral_worktree_paths_for_commit(worktree_path)
        self._restore_uncommitted_submodule_pointers(worktree_path, submodule_results)
        self._run_git(["add", "-A"], cwd=worktree_path)
        self._remove_generated_paths_from_index(worktree_path)
        self._restore_uncommitted_submodule_pointers(worktree_path, submodule_results)
        status = self._run_git(["status", "--porcelain"], cwd=worktree_path).stdout.strip()
        staged_status = self._staged_worktree_status(worktree_path)
        if not staged_status:
            result: dict[str, Any] = {"committed": False, "reason": "no_changes"}
            if status:
                result["status"] = status
            if submodule_results:
                result["submodule_results"] = submodule_results
            return result
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
        result = {
            "committed": True,
            "commit": commit_ref,
            "status": status,
        }
        if submodule_results:
            result["submodule_results"] = submodule_results
        return result

    def _commit_worktree_submodule_changes(
        self,
        worktree_path: Path,
        task: PortalTask,
        attempt: int,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for relative in WORKTREE_SUBMODULE_PATHS:
            target = worktree_path / relative
            if not self._is_git_worktree(target):
                continue
            nested_results = self._commit_nested_submodule_changes(
                target,
                task,
                attempt,
                parent_relative=relative,
            )
            self._restore_ephemeral_worktree_paths_for_commit(target)
            self._run_git(["add", "-A"], cwd=target)
            self._remove_generated_paths_from_index(target)
            status = self._run_git(["status", "--porcelain"], cwd=target).stdout.strip()
            staged_status = self._staged_worktree_status(target)
            if not staged_status:
                result: dict[str, Any] = {"path": relative, "committed": False, "reason": "no_changes"}
                if status:
                    result["status"] = status
                if nested_results:
                    result["nested_submodule_results"] = nested_results
                results.append(result)
                continue
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
                    "-m",
                    f"Submodule: {relative}",
                ],
                cwd=target,
            )
            commit_ref = self._run_git(["rev-parse", "HEAD"], cwd=target).stdout.strip()
            result = {"path": relative, "committed": True, "commit": commit_ref, "status": status}
            if nested_results:
                result["nested_submodule_results"] = nested_results
            results.append(result)
        return results

    def _commit_nested_submodule_changes(
        self,
        worktree_path: Path,
        task: PortalTask,
        attempt: int,
        *,
        parent_relative: str,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for relative in self._declared_submodule_paths(worktree_path):
            full_relative = f"{parent_relative.rstrip('/')}/{relative}"
            target = worktree_path / relative
            if not self._is_git_worktree(target):
                continue
            nested_results = self._commit_nested_submodule_changes(
                target,
                task,
                attempt,
                parent_relative=full_relative,
            )
            self._restore_ephemeral_worktree_paths_for_commit(target)
            self._run_git(["add", "-A"], cwd=target)
            self._remove_generated_paths_from_index(target)
            status = self._run_git(["status", "--porcelain"], cwd=target).stdout.strip()
            staged_status = self._staged_worktree_status(target)
            if not staged_status:
                result: dict[str, Any] = {
                    "path": full_relative,
                    "committed": False,
                    "reason": "no_changes",
                }
                if status:
                    result["status"] = status
                if nested_results:
                    result["nested_submodule_results"] = nested_results
                results.append(result)
                continue
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
                    "-m",
                    f"Submodule: {full_relative}",
                ],
                cwd=target,
            )
            commit_ref = self._run_git(["rev-parse", "HEAD"], cwd=target).stdout.strip()
            result = {"path": full_relative, "committed": True, "commit": commit_ref, "status": status}
            if nested_results:
                result["nested_submodule_results"] = nested_results
            results.append(result)
        return results

    def _restore_uncommitted_submodule_pointers(
        self,
        worktree_path: Path,
        submodule_results: list[dict[str, Any]],
    ) -> None:
        for result in submodule_results:
            if result.get("committed", False):
                continue
            relative = str(result.get("path") or "")
            if relative not in WORKTREE_SUBMODULE_PATHS or not self._repo_relative_path_safe(relative):
                continue
            subprocess.run(
                ["git", "restore", "--source=HEAD", "--staged", "--worktree", "--", relative],
                cwd=worktree_path,
                text=True,
                capture_output=True,
                check=False,
            )

    def _preserve_failed_validation_worktree(
        self,
        worktree_path: Path,
        branch_name: str,
        task: PortalTask,
        attempt: int,
        validation_result: dict[str, Any],
    ) -> dict[str, Any]:
        started_at = utc_now()
        commit_result = self._commit_worktree_changes(worktree_path, task, attempt)
        rescue_branch = ""
        implementation_commit = str(commit_result.get("commit", ""))
        if implementation_commit:
            rescue_branch = self._failed_validation_rescue_branch_name(branch_name)
            self._run_git(["branch", "-f", rescue_branch, implementation_commit], cwd=self.repo_root)
        cleanup_result = self._cleanup_merged_worktree(worktree_path, branch_name)
        result = {
            "task_id": task.task_id,
            "attempt": attempt,
            "branch": branch_name,
            "worktree_path": str(worktree_path),
            "started_at": started_at,
            "finished_at": utc_now(),
            "preserved": bool(implementation_commit),
            "rescue_branch": rescue_branch,
            "implementation_commit": implementation_commit,
            "commit_result": commit_result,
            "cleanup_result": cleanup_result,
            "validation_result": validation_result,
        }
        self._record_event("failed_validation_worktree_preserved", result)
        return result

    @staticmethod
    def _failed_validation_rescue_branch_name(branch_name: str) -> str:
        safe_name = branch_name.removeprefix("implementation/").strip("/").replace(" ", "-")
        return f"rescue/{safe_name or 'implementation-attempt'}-failed-validation"

    def _restore_ephemeral_worktree_paths_for_commit(self, worktree_path: Path) -> None:
        for relative in EPHEMERAL_WORKTREE_PATHS:
            self._restore_or_remove_generated_path_for_commit(worktree_path, relative)
        for relative in sorted(self._dirty_worktree_paths(worktree_path)):
            if self._path_is_generated_worktree_artifact(relative):
                self._restore_or_remove_generated_path_for_commit(worktree_path, relative)

    def _remove_generated_paths_from_index(self, worktree_path: Path) -> None:
        for relative in self._staged_worktree_paths(worktree_path):
            if self._path_is_generated_worktree_artifact(relative):
                self._restore_or_remove_generated_path_for_commit(worktree_path, relative)

    def _restore_or_remove_generated_path_for_commit(self, worktree_path: Path, relative: str) -> None:
        if not self._repo_relative_path_safe(relative):
            return
        target = worktree_path / relative
        if relative in WORKTREE_SUBMODULE_PATHS and target.is_symlink():
            target.unlink()
        if self._path_tracked_in_head(worktree_path, relative) or self._path_tracked_in_repo(worktree_path, relative):
            restore = subprocess.run(
                ["git", "restore", "--source=HEAD", "--staged", "--worktree", "--", relative],
                cwd=worktree_path,
                text=True,
                capture_output=True,
                check=False,
            )
            if restore.returncode == 0:
                return
        subprocess.run(
            ["git", "restore", "--staged", "--", relative],
            cwd=worktree_path,
            text=True,
            capture_output=True,
            check=False,
        )
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)

    def _path_is_generated_worktree_artifact(self, relative: str) -> bool:
        if not self._repo_relative_path_safe(relative):
            return False
        normalized = relative.strip("/")
        parts = Path(normalized).parts
        if any(part in GENERATED_WORKTREE_DIR_NAMES for part in parts):
            return True
        if normalized.endswith(GENERATED_WORKTREE_SUFFIXES):
            return True
        return any(self._path_matches_prefix(normalized, prefix) for prefix in EPHEMERAL_WORKTREE_PATHS)

    def _staged_worktree_paths(self, cwd: Path) -> list[str]:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "-z"],
            cwd=cwd,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        paths = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
        return [path for path in paths if path]

    def _staged_worktree_status(self, cwd: Path) -> str:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-status"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _path_tracked_in_repo(self, cwd: Path, relative: str) -> bool:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def _path_tracked_in_head(self, cwd: Path, relative: str) -> bool:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", relative],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        return any(line == relative or line.startswith(f"{relative.rstrip('/')}/") for line in result.stdout.splitlines())

    def _run_validation_commands(
        self,
        workspace_path: Path,
        task: PortalTask,
        log_path: Path,
        *,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
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
            if env and env.get("PLAYWRIGHT_PORT"):
                log_fh.write(f"Environment: PLAYWRIGHT_PORT={env['PLAYWRIGHT_PORT']}\n")
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
                        env=env,
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

    def _main_branch_name(self) -> str:
        for candidate in ("main", "master"):
            if self._git_ref_exists(candidate):
                return candidate
        current_branch = self._git_current_branch(self.repo_root)
        return current_branch or "HEAD"

    def _main_merge_worktree_root(self) -> Path:
        return self.worktree_root / ".main-merge-worktrees"

    @staticmethod
    def _safe_ref_path_fragment(ref: str) -> str:
        safe = "".join(character if character.isalnum() or character in "-._" else "-" for character in ref)
        return safe.strip("-") or "main"

    def _git_worktree_entries(self) -> list[dict[str, str]]:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current:
                    entries.append(current)
                current = {"worktree": line.split(" ", 1)[1]}
            elif line.startswith("branch "):
                branch = line.split(" ", 1)[1]
                current["branch"] = branch.removeprefix("refs/heads/")
        if current:
            entries.append(current)
        return entries

    def _branch_checked_out_worktree_paths(self, branch_name: str) -> list[Path]:
        paths: list[Path] = []
        for entry in self._git_worktree_entries():
            if entry.get("branch") != branch_name:
                continue
            worktree = entry.get("worktree")
            if worktree:
                paths.append(Path(worktree))
        return paths

    @staticmethod
    def _path_is_under(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            return False
        return True

    def _prepare_main_merge_workspace(self, target_branch: str, branch_name: str) -> dict[str, Any]:
        if self._git_current_branch(self.repo_root) == target_branch:
            return {
                "available": True,
                "path": str(self.repo_root),
                "ephemeral": False,
                "target_branch": target_branch,
            }

        merge_root = self._main_merge_worktree_root()
        checked_out_paths = self._branch_checked_out_worktree_paths(target_branch)
        for checked_out_path in checked_out_paths:
            if checked_out_path.resolve() == self.repo_root.resolve():
                return {
                    "available": True,
                    "path": str(self.repo_root),
                    "ephemeral": False,
                    "target_branch": target_branch,
                }
            if self._path_is_under(checked_out_path, merge_root):
                dirty_paths = sorted(self._dirty_worktree_paths(checked_out_path))
                if dirty_paths:
                    return {
                        "available": False,
                        "reason": "main_merge_worktree_dirty",
                        "target_branch": target_branch,
                        "worktree_path": str(checked_out_path),
                        "dirty_paths": dirty_paths,
                    }
                self._run_git(["worktree", "remove", "--force", str(checked_out_path)], cwd=self.repo_root)
                continue
            return {
                "available": False,
                "reason": "main_branch_checked_out_elsewhere",
                "target_branch": target_branch,
                "worktree_path": str(checked_out_path),
            }

        merge_root.mkdir(parents=True, exist_ok=True)
        safe_target = self._safe_ref_path_fragment(target_branch)
        safe_branch = self._safe_ref_path_fragment(branch_name)
        workspace = merge_root / f"{safe_target}-{safe_branch}-{os.getpid()}-{int(time.time())}"
        self._run_git(["worktree", "add", str(workspace), target_branch], cwd=self.repo_root)
        return {
            "available": True,
            "path": str(workspace),
            "ephemeral": True,
            "target_branch": target_branch,
        }

    def _cleanup_main_merge_workspace(self, workspace_path: Path, *, ephemeral: bool) -> dict[str, Any]:
        if not ephemeral:
            return {"cleaned": True, "removed": False, "worktree_path": str(workspace_path)}
        if not workspace_path.exists():
            return {"cleaned": True, "removed": False, "worktree_path": str(workspace_path)}
        remove = subprocess.run(
            ["git", "worktree", "remove", "--force", str(workspace_path)],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        return {
            "cleaned": remove.returncode == 0,
            "removed": remove.returncode == 0,
            "worktree_path": str(workspace_path),
            "returncode": remove.returncode,
            "stdout": remove.stdout[-4000:],
            "stderr": remove.stderr[-4000:],
        }

    def _merge_branch_to_main(
        self,
        branch_name: str,
        task: PortalTask,
        attempt: int,
        *,
        baseline_ref: str = "",
    ) -> dict[str, Any]:
        started_at = utc_now()
        target_branch = self._main_branch_name()
        if baseline_ref and not self._git_ref_is_ancestor(baseline_ref, target_branch):
            result = {
                "attempted": False,
                "merged": False,
                "returncode": 2,
                "branch": branch_name,
                "target_branch": target_branch,
                "baseline_ref": baseline_ref,
                "started_at": started_at,
                "finished_at": utc_now(),
                "merge_commit": "",
                "stdout": "",
                "stderr": "",
                "reason": "baseline_not_ancestor_of_target",
                "identical_untracked_paths": [],
                "submodule_merge_results": [],
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
                "target_branch": target_branch,
                "started_at": started_at,
                "identical_untracked_paths": [],
            }
            if existing_lock:
                result["lock_owner_pid"] = int(existing_lock.get("pid") or 0)
                result["lock_owner_branch"] = str(existing_lock.get("branch") or "")
            return result

        merge_workspace: Path | None = None
        merge_workspace_ephemeral = False
        removed_untracked: dict[str, bytes] = {}
        try:
            self._write_lock_metadata(lock_fd, lock_metadata)
            workspace_result = self._prepare_main_merge_workspace(target_branch, branch_name)
            if not workspace_result.get("available", False):
                result = {
                    "attempted": True,
                    "merged": False,
                    "returncode": 2,
                    "branch": branch_name,
                    "target_branch": target_branch,
                    "started_at": started_at,
                    "finished_at": utc_now(),
                    "merge_commit": "",
                    "stdout": "",
                    "stderr": "",
                    "reason": str(workspace_result.get("reason") or "main_merge_workspace_unavailable"),
                    "dirty_paths": workspace_result.get("dirty_paths", []),
                    "main_worktree_path": str(workspace_result.get("worktree_path") or ""),
                    "identical_untracked_paths": [],
                    "submodule_merge_results": [],
                }
                self._record_event("merge_finished", result)
                return result

            merge_workspace = Path(str(workspace_result["path"]))
            merge_workspace_ephemeral = bool(workspace_result.get("ephemeral", False))
            resolved_add_add_conflicts = self._resolve_generated_add_add_conflicts(cwd=merge_workspace)
            identical_untracked_paths = self._identical_untracked_merge_paths(branch_name, cwd=merge_workspace)
            dirty_overlap = self._dirty_merge_conflict_paths(
                branch_name,
                cwd=merge_workspace,
                ignore_paths=set(identical_untracked_paths),
            )
            if dirty_overlap:
                result = {
                    "attempted": True,
                    "merged": False,
                    "returncode": 2,
                    "branch": branch_name,
                    "target_branch": target_branch,
                    "started_at": started_at,
                    "finished_at": utc_now(),
                    "merge_commit": "",
                    "stdout": "",
                    "stderr": "",
                    "reason": "main_checkout_dirty_conflict",
                    "dirty_paths": dirty_overlap,
                    "main_worktree_path": str(merge_workspace),
                    "used_ephemeral_main_worktree": merge_workspace_ephemeral,
                    "identical_untracked_paths": identical_untracked_paths,
                    "resolved_generated_conflicts": resolved_add_add_conflicts,
                    "submodule_merge_results": [],
                }
                self._record_event("merge_finished", result)
                return result

            removed_untracked = self._remove_untracked_paths_for_merge(identical_untracked_paths, cwd=merge_workspace)
            self._record_event(
                "merge_started",
                {
                    "task_id": task.task_id,
                    "attempt": attempt,
                    "branch": branch_name,
                    "target_branch": target_branch,
                    "main_worktree_path": str(merge_workspace),
                    "used_ephemeral_main_worktree": merge_workspace_ephemeral,
                    "started_at": started_at,
                    "resolved_generated_conflicts": resolved_add_add_conflicts,
                },
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
                cwd=merge_workspace,
                text=True,
                capture_output=True,
                check=False,
            )
            finished_at = utc_now()
            merge_commit = ""
            submodule_merge_results: list[dict[str, Any]] = []
            submodule_conflict_repair: dict[str, Any] = {}
            merge_abort_result: dict[str, Any] = {}
            merge_returncode = merge.returncode
            if merge_returncode != 0:
                submodule_conflict_repair = self._repair_submodule_gitlink_merge_conflicts(
                    merge_workspace,
                    task=task,
                )
                if submodule_conflict_repair.get("repaired", False):
                    merge_returncode = 0
                else:
                    merge_abort_result = self._abort_failed_merge(merge_workspace)
            if merge_returncode == 0:
                merge_commit = self._run_git(["rev-parse", "HEAD"], cwd=merge_workspace).stdout.strip()
                submodule_merge_results = self._merge_submodule_branches_to_main(branch_name)
            elif removed_untracked:
                self._restore_removed_untracked_paths(removed_untracked, cwd=merge_workspace)
            failed_submodules = [item for item in submodule_merge_results if not item.get("merged", False)]
            effective_returncode = merge_returncode
            effective_merged = merge_returncode == 0 and not failed_submodules
            result = {
                "attempted": True,
                "merged": effective_merged,
                "returncode": 2 if failed_submodules else effective_returncode,
                "branch": branch_name,
                "target_branch": target_branch,
                "command": command,
                "started_at": started_at,
                "finished_at": finished_at,
                "merge_commit": merge_commit,
                "stdout": merge.stdout[-4000:],
                "stderr": merge.stderr[-4000:],
                "main_worktree_path": str(merge_workspace),
                "used_ephemeral_main_worktree": merge_workspace_ephemeral,
                "identical_untracked_paths": identical_untracked_paths,
                "resolved_generated_conflicts": resolved_add_add_conflicts,
                "submodule_merge_results": submodule_merge_results,
            }
            if submodule_conflict_repair:
                result["submodule_conflict_repair"] = submodule_conflict_repair
            if merge_abort_result:
                result["merge_abort_result"] = merge_abort_result
            if failed_submodules:
                result["submodule_merge_failed"] = True
                result["reason"] = "submodule_merge_failed"
            self._record_event("merge_finished", result)
            return result
        finally:
            if merge_workspace is not None:
                merge_workspace_cleanup = self._cleanup_main_merge_workspace(
                    merge_workspace,
                    ephemeral=merge_workspace_ephemeral,
                )
                if not merge_workspace_cleanup.get("cleaned", False):
                    self._record_event("main_merge_worktree_cleanup_failed", merge_workspace_cleanup)
            try:
                if merge_lock.exists():
                    merge_lock.unlink()
            except OSError:
                logger.warning("Failed to remove merge lock %s", merge_lock)

    def _abort_failed_merge(self, cwd: Path) -> dict[str, Any]:
        merge_head = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "MERGE_HEAD"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if merge_head.returncode != 0:
            return {"attempted": False, "reason": "no_merge_in_progress"}
        abort = subprocess.run(
            ["git", "merge", "--abort"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        result = {
            "attempted": True,
            "aborted": abort.returncode == 0,
            "returncode": abort.returncode,
            "stdout": abort.stdout[-4000:],
            "stderr": abort.stderr[-4000:],
        }
        self._record_event("failed_merge_aborted", {"worktree_path": str(cwd), **result})
        return result

    def _repair_submodule_gitlink_merge_conflicts(
        self,
        workspace: Path,
        *,
        task: PortalTask,
    ) -> dict[str, Any]:
        conflicts = self._unmerged_gitlink_conflicts(workspace)
        if not conflicts:
            return {"repaired": False, "reason": "no_gitlink_conflicts"}
        repairs: list[dict[str, Any]] = []
        for relative, stages in conflicts.items():
            selected_commit = self._select_submodule_gitlink_resolution(relative, stages, task=task)
            if not selected_commit:
                repairs.append(
                    {
                        "path": relative,
                        "repaired": False,
                        "reason": "no_safe_resolution",
                        "stages": stages,
                    }
                )
                continue
            update = subprocess.run(
                ["git", "update-index", "--add", "--cacheinfo", f"160000,{selected_commit},{relative}"],
                cwd=workspace,
                text=True,
                capture_output=True,
                check=False,
            )
            repairs.append(
                {
                    "path": relative,
                    "repaired": update.returncode == 0,
                    "reason": "selected_current_equivalent_submodule_head"
                    if update.returncode == 0
                    else "update_index_failed",
                    "selected_commit": selected_commit,
                    "stages": stages,
                    "returncode": update.returncode,
                    "stdout": update.stdout[-4000:],
                    "stderr": update.stderr[-4000:],
                }
            )
        unresolved = self._unmerged_worktree_paths(workspace)
        if unresolved:
            result = {
                "repaired": False,
                "reason": "unresolved_paths_remain",
                "repairs": repairs,
                "unresolved_paths": sorted(unresolved),
            }
            self._record_event("submodule_gitlink_conflict_repair", result)
            return result
        commit = subprocess.run(
            [
                "git",
                "-c",
                "user.name=Implementation Daemon",
                "-c",
                "user.email=implementation-daemon@example.invalid",
                "commit",
                "--no-edit",
            ],
            cwd=workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        if commit.returncode != 0:
            result = {
                "repaired": False,
                "reason": "merge_commit_failed",
                "repairs": repairs,
                "returncode": commit.returncode,
                "stdout": commit.stdout[-4000:],
                "stderr": commit.stderr[-4000:],
            }
            self._record_event("submodule_gitlink_conflict_repair", result)
            return result
        merge_commit = self._run_git(["rev-parse", "HEAD"], cwd=workspace).stdout.strip()
        result = {
            "repaired": True,
            "reason": "committed_resolved_gitlinks",
            "repairs": repairs,
            "merge_commit": merge_commit,
            "stdout": commit.stdout[-4000:],
            "stderr": commit.stderr[-4000:],
        }
        self._record_event("submodule_gitlink_conflict_repair", result)
        return result

    def _unmerged_gitlink_conflicts(self, cwd: Path) -> dict[str, dict[str, str]]:
        result = subprocess.run(
            ["git", "ls-files", "-u", "-z"],
            cwd=cwd,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return {}
        conflicts: dict[str, dict[str, str]] = {}
        for raw_entry in result.stdout.split(b"\0"):
            if not raw_entry:
                continue
            try:
                metadata, raw_path = raw_entry.split(b"\t", 1)
                mode, object_id, stage = metadata.decode("ascii").split()
            except ValueError:
                continue
            if mode != "160000":
                continue
            relative = raw_path.decode("utf-8", errors="surrogateescape")
            if not self._repo_relative_path_safe(relative):
                continue
            conflicts.setdefault(relative, {})[stage] = object_id
        return conflicts

    def _select_submodule_gitlink_resolution(
        self,
        relative: str,
        stages: dict[str, str],
        *,
        task: PortalTask,
    ) -> str:
        source = (self.repo_root / relative).resolve()
        if not self._is_git_worktree(source):
            return ""
        if self._run_git(["status", "--porcelain"], cwd=source).stdout.strip():
            return ""
        head = self._run_git(["rev-parse", "HEAD"], cwd=source).stdout.strip()
        theirs = stages.get("3", "")
        if theirs and self._git_ref_is_ancestor_in_repo(source, theirs, head):
            return head
        if task.task_id and self._submodule_head_has_task_commit(source, task.task_id):
            return head
        return ""

    def _submodule_head_has_task_commit(self, source: Path, task_id: str) -> bool:
        result = subprocess.run(
            ["git", "log", "--format=%H", "--fixed-strings", f"--grep={task_id}:", "HEAD"],
            cwd=source,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())

    def _merge_submodule_branches_to_main(self, branch_name: str) -> list[dict[str, Any]]:
        return self._merge_submodule_branches_to_main_in_repo(
            repo_path=self.repo_root,
            branch_name=branch_name,
            parent_relative="",
        )

    def _merge_submodule_branches_to_main_in_repo(
        self,
        *,
        repo_path: Path,
        branch_name: str,
        parent_relative: str,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        relatives = WORKTREE_SUBMODULE_PATHS if not parent_relative else tuple(self._declared_submodule_paths(repo_path))
        for relative in relatives:
            full_relative = f"{parent_relative.rstrip('/')}/{relative}" if parent_relative else relative
            source = (self.repo_root / full_relative).resolve()
            submodule_branch = self._submodule_worktree_branch_name(branch_name, full_relative)
            if not self._is_git_worktree(source):
                continue
            if not self._git_ref_exists_in_repo(source, submodule_branch):
                continue
            default_branch = self._submodule_default_branch(relative, source)
            dirty = self._run_git(["status", "--porcelain"], cwd=source).stdout.strip()
            if dirty:
                results.append(
                    {
                        "path": relative,
                        "branch": submodule_branch,
                        "default_branch": default_branch,
                        "merged": False,
                        "reason": "submodule_checkout_dirty",
                        "status": dirty,
                    }
                )
                continue
            if self._git_ref_is_ancestor_in_repo(source, submodule_branch, default_branch):
                results.append(
                    {
                        "path": relative,
                        "branch": submodule_branch,
                        "default_branch": default_branch,
                        "merged": True,
                        "reason": "already_merged",
                    }
                )
                continue
            if self._git_current_branch(source) != default_branch:
                checkout = subprocess.run(
                    ["git", "checkout", default_branch],
                    cwd=source,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if checkout.returncode != 0:
                    results.append(
                        {
                            "path": relative,
                            "branch": submodule_branch,
                            "default_branch": default_branch,
                            "merged": False,
                            "returncode": checkout.returncode,
                            "reason": "default_branch_checkout_failed",
                            "stdout": checkout.stdout[-4000:],
                            "stderr": checkout.stderr[-4000:],
                        }
                    )
                    continue
            merge = subprocess.run(
                ["git", "merge", "--ff-only", submodule_branch],
                cwd=source,
                text=True,
                capture_output=True,
                check=False,
            )
            result = {
                "path": full_relative,
                "branch": submodule_branch,
                "default_branch": default_branch,
                "merged": merge.returncode == 0,
                "returncode": merge.returncode,
                "stdout": merge.stdout[-4000:],
                "stderr": merge.stderr[-4000:],
                "commit": "",
            }
            if merge.returncode == 0:
                result["commit"] = self._run_git(["rev-parse", "HEAD"], cwd=source).stdout.strip()
            results.append(result)
            if merge.returncode == 0:
                results.extend(
                    self._merge_submodule_branches_to_main_in_repo(
                        repo_path=source,
                        branch_name=branch_name,
                        parent_relative=full_relative,
                    )
                )
        return results

    def _submodule_default_branch(self, relative: str, source: Path) -> str:
        result = subprocess.run(
            ["git", "config", "--file", str(self.repo_root / ".gitmodules"), "--get-regexp", r"^submodule\..*\.path$"],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                key, _, path_value = line.partition(" ")
                if path_value.strip() != relative:
                    continue
                module_key = key.rsplit(".", 1)[0]
                branch = subprocess.run(
                    ["git", "config", "--file", str(self.repo_root / ".gitmodules"), "--get", f"{module_key}.branch"],
                    cwd=self.repo_root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if branch.returncode == 0 and branch.stdout.strip():
                    return branch.stdout.strip()
        current = self._git_current_branch(source)
        return current or "main"

    def _git_ref_is_ancestor_in_repo(self, cwd: Path, ancestor: str, descendant: str) -> bool:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def _cleanup_merged_worktree(self, worktree_path: Path | None, branch_name: str) -> dict[str, Any]:
        started_at = utc_now()
        removed_worktree = False
        deleted_branch = False
        submodule_cleanup: list[dict[str, Any]] = []
        errors: list[str] = []
        try:
            if worktree_path is not None:
                submodule_cleanup = self._cleanup_worktree_submodules(worktree_path, branch_name)
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
                "submodule_cleanup": submodule_cleanup,
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
            "submodule_cleanup": submodule_cleanup,
        }
        self._record_event("cleanup_finished", result)
        return result

    def _cleanup_worktree_submodules(
        self,
        worktree_path: Path,
        branch_name: str,
        *,
        parent_relative: str = "",
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        relatives = WORKTREE_SUBMODULE_PATHS if not parent_relative else tuple(self._declared_submodule_paths(worktree_path))
        for relative in relatives:
            full_relative = f"{parent_relative.rstrip('/')}/{relative}" if parent_relative else relative
            source = (self.repo_root / full_relative).resolve()
            target = worktree_path / relative
            submodule_branch = self._submodule_worktree_branch_name(branch_name, full_relative)
            if not self._is_git_worktree(source):
                continue
            removed_worktree = False
            deleted_branch = False
            nested_cleanup: list[dict[str, Any]] = []
            errors: list[str] = []
            if self._is_git_worktree(target):
                nested_cleanup = self._cleanup_worktree_submodules(
                    target,
                    branch_name,
                    parent_relative=full_relative,
                )
                remove = subprocess.run(
                    ["git", "worktree", "remove", "--force", str(target)],
                    cwd=source,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if remove.returncode == 0:
                    removed_worktree = True
                else:
                    errors.append((remove.stderr or remove.stdout).strip())
            default_branch = self._submodule_default_branch(relative, source)
            if self._git_ref_exists_in_repo(source, submodule_branch) and self._git_ref_is_ancestor_in_repo(
                source, submodule_branch, default_branch
            ):
                delete = subprocess.run(
                    ["git", "branch", "-D", submodule_branch],
                    cwd=source,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if delete.returncode == 0:
                    deleted_branch = True
                else:
                    errors.append((delete.stderr or delete.stdout).strip())
            results.append(
                {
                    "path": full_relative,
                    "branch": submodule_branch,
                    "removed_worktree": removed_worktree,
                    "deleted_branch": deleted_branch,
                    "cleaned": not errors,
                    "errors": errors,
                    "nested_submodule_cleanup": nested_cleanup,
                }
            )
        return results

    def _dirty_merge_conflict_paths(
        self,
        branch_name: str,
        *,
        cwd: Path | None = None,
        ignore_paths: set[str] | None = None,
    ) -> list[str]:
        workspace = cwd or self.repo_root
        dirty_paths = self._dirty_worktree_paths(workspace)
        if not dirty_paths:
            return []
        branch_paths = self._branch_changed_paths(branch_name)
        overlap = dirty_paths & branch_paths
        if ignore_paths:
            overlap -= ignore_paths
        return sorted(overlap)

    def _resolve_generated_add_add_conflicts(self, *, cwd: Path | None = None) -> list[dict[str, Any]]:
        workspace = cwd or self.repo_root
        results: list[dict[str, Any]] = []
        for relative in self._unmerged_add_add_paths(workspace):
            if not self._generated_add_add_conflict_path_allowed(relative):
                continue
            ours = self._conflict_stage_blob(workspace, relative, stage=2)
            theirs = self._conflict_stage_blob(workspace, relative, stage=3)
            selected = self._select_generated_conflict_blob(ours, theirs)
            if selected is None:
                results.append(
                    {
                        "path": relative,
                        "resolved": False,
                        "reason": "contents_not_equivalent_or_contained",
                    }
                )
                continue
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(selected)
            add = subprocess.run(
                ["git", "add", "--", relative],
                cwd=workspace,
                text=True,
                capture_output=True,
                check=False,
            )
            results.append(
                {
                    "path": relative,
                    "resolved": add.returncode == 0,
                    "reason": "selected_equivalent_generated_content" if add.returncode == 0 else "git_add_failed",
                    "returncode": add.returncode,
                    "stdout": add.stdout[-4000:],
                    "stderr": add.stderr[-4000:],
                }
            )
        if results:
            self._record_event(
                "generated_add_add_conflict_repair",
                {"main_worktree_path": str(workspace), "results": results},
            )
        return results

    def _unmerged_add_add_paths(self, cwd: Path) -> list[str]:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            cwd=cwd,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        paths: list[str] = []
        for raw_entry in result.stdout.split(b"\0"):
            if not raw_entry or len(raw_entry) < 4:
                continue
            status = raw_entry[:2].decode("ascii", errors="ignore")
            if status != "AA":
                continue
            relative = raw_entry[3:].decode("utf-8", errors="surrogateescape")
            if relative:
                paths.append(relative)
        return paths

    def _generated_add_add_conflict_path_allowed(self, relative: str) -> bool:
        if not self._repo_relative_path_safe(relative):
            return False
        normalized = relative.strip("/")
        return any(self._path_matches_prefix(normalized, prefix) for prefix in GENERATED_ADD_ADD_CONFLICT_PREFIXES)

    def _conflict_stage_blob(self, cwd: Path, relative: str, *, stage: int) -> bytes | None:
        result = subprocess.run(
            ["git", "show", f":{stage}:{relative}"],
            cwd=cwd,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout

    @staticmethod
    def _select_generated_conflict_blob(ours: bytes | None, theirs: bytes | None) -> bytes | None:
        if ours is None or theirs is None:
            return None
        if ours == theirs:
            return ours
        if ours and ours in theirs:
            return theirs
        if theirs and theirs in ours:
            return ours
        return None

    def _identical_untracked_merge_paths(self, branch_name: str, *, cwd: Path | None = None) -> list[str]:
        workspace = cwd or self.repo_root
        branch_paths = self._branch_changed_paths(branch_name)
        if not branch_paths:
            return []
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=workspace,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        untracked_paths = {
            path
            for path in result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
            if path and path in branch_paths
        }
        identical: list[str] = []
        for relative in sorted(untracked_paths):
            if not self._repo_relative_path_safe(relative):
                continue
            source = workspace / relative
            if not source.is_file() or source.is_symlink():
                continue
            branch_blob = subprocess.run(
                ["git", "show", f"{branch_name}:{relative}"],
                cwd=self.repo_root,
                capture_output=True,
                check=False,
            )
            if branch_blob.returncode == 0 and source.read_bytes() == branch_blob.stdout:
                identical.append(relative)
        return identical

    def _remove_untracked_paths_for_merge(self, paths: list[str], *, cwd: Path | None = None) -> dict[str, bytes]:
        workspace = cwd or self.repo_root
        removed: dict[str, bytes] = {}
        for relative in paths:
            if not self._repo_relative_path_safe(relative):
                continue
            source = workspace / relative
            if not source.is_file() or source.is_symlink():
                continue
            removed[relative] = source.read_bytes()
            source.unlink()
        return removed

    def _restore_removed_untracked_paths(self, removed: dict[str, bytes], *, cwd: Path | None = None) -> None:
        workspace = cwd or self.repo_root
        for relative, content in removed.items():
            if not self._repo_relative_path_safe(relative):
                continue
            target = workspace / relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    @staticmethod
    def _repo_relative_path_safe(relative: str) -> bool:
        if not relative or relative.startswith("/") or "\0" in relative:
            return False
        return ".." not in Path(relative).parts

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

    def _branch_changed_paths(self, branch_name: str, *, base_ref: str | None = None) -> set[str]:
        base = base_ref or self._branch_merge_base(branch_name, self._main_branch_name())
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}..{branch_name}"],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _branch_merge_base(self, branch_name: str, target_branch: str) -> str:
        result = subprocess.run(
            ["git", "merge-base", target_branch, branch_name],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return target_branch

    def _reconcile_failed_merges(self, *, skip_task_ids: set[str] | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        target_branch = self._main_branch_name()
        for event in self._failed_merge_candidates(skip_task_ids=skip_task_ids):
            task_id = str(event.get("task_id") or "")
            attempt = int(event.get("attempt") or 0)
            branch = str(event.get("branch") or "")
            worktree_path_text = str(event.get("worktree_path") or "")
            worktree_path = Path(worktree_path_text) if worktree_path_text else None
            implementation_commit = str(event.get("implementation_commit") or "")
            if not task_id or not implementation_commit:
                continue
            if self._git_ref_is_ancestor(implementation_commit, target_branch):
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
            merge_result = self._merge_branch_to_main(
                branch,
                task,
                attempt,
                baseline_ref=str(event.get("baseline_ref") or ""),
            )
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

    def _failed_merge_candidates(self, *, skip_task_ids: set[str] | None = None) -> list[dict[str, Any]]:
        skip_task_ids = skip_task_ids or set()
        candidates: dict[tuple[str, str], dict[str, Any]] = {}
        reconciled_commits: set[str] = set()
        abandoned_commits: set[str] = set()
        target_branch = self._main_branch_name()
        for event in self._iter_events():
            if str(event.get("type") or "") == "merge_reconciled":
                implementation_commit = str(event.get("implementation_commit") or "")
                merge_result = event.get("merge_result") or {}
                merge_reason = merge_result.get("reason") if isinstance(merge_result, dict) else ""
                if implementation_commit and event.get("resolved"):
                    reconciled_commits.add(implementation_commit)
                elif implementation_commit and merge_reason == "baseline_not_ancestor_of_target":
                    abandoned_commits.add(implementation_commit)
                continue
            if str(event.get("type") or "") != "implementation_finished":
                continue
            task_id = str(event.get("task_id") or "")
            if task_id in skip_task_ids:
                continue
            implementation_commit = str(event.get("implementation_commit") or "")
            if (
                not implementation_commit
                or implementation_commit in reconciled_commits
                or implementation_commit in abandoned_commits
            ):
                continue
            validation = event.get("validation_result") or {}
            if isinstance(validation, dict) and validation.get("attempted") and not validation.get("passed", False):
                continue
            merge_result = event.get("merge_result") or {}
            if not isinstance(merge_result, dict):
                continue
            if not merge_result.get("attempted") or merge_result.get("merged"):
                continue
            key = (task_id, implementation_commit)
            candidates[key] = event

        unresolved: list[dict[str, Any]] = []
        for event in candidates.values():
            implementation_commit = str(event.get("implementation_commit") or "")
            if implementation_commit in reconciled_commits or implementation_commit in abandoned_commits:
                continue
            if implementation_commit and not self._git_ref_is_ancestor(implementation_commit, target_branch):
                unresolved.append(event)
                continue
            cleanup = event.get("cleanup_result") or {}
            if isinstance(cleanup, dict) and not cleanup.get("cleaned", False):
                unresolved.append(event)
        return unresolved

    def _unresolved_merge_failures_by_task(self, *, skip_task_ids: set[str] | None = None) -> dict[str, dict[str, Any]]:
        skip_task_ids = skip_task_ids or set()
        failures: dict[str, dict[str, Any]] = {}
        target_branch = self._main_branch_name()
        for event in self._failed_merge_candidates(skip_task_ids=skip_task_ids):
            task_id = str(event.get("task_id") or "")
            if task_id in skip_task_ids:
                continue
            implementation_commit = str(event.get("implementation_commit") or "")
            if task_id and implementation_commit and not self._git_ref_is_ancestor(implementation_commit, target_branch):
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
        return not self._git_ref_is_ancestor(previous.last_implementation_commit, self._main_branch_name())

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

    def _successfully_merged_task_ids(self) -> set[str]:
        task_ids: set[str] = set()
        target_branch = self._main_branch_name()
        for event in self._iter_events():
            event_type = str(event.get("type") or "")
            task_id = str(event.get("task_id") or "")
            if not task_id:
                continue
            implementation_commit = str(event.get("implementation_commit") or "")
            if event_type == "implementation_finished":
                merge_result = event.get("merge_result") or {}
                if not isinstance(merge_result, dict) or not merge_result.get("merged"):
                    continue
            elif event_type == "merge_reconciled":
                if not event.get("resolved"):
                    continue
            else:
                continue
            if implementation_commit and not self._git_ref_is_ancestor(implementation_commit, target_branch):
                continue
            task_ids.add(task_id)
        return task_ids

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
        copilot = shutil.which("copilot")
        if copilot:
            return _copilot_fallback_command(codex=codex, copilot=copilot, workspace_path=workspace_path)
        if codex:
            return [
                codex,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "-C",
                str(workspace_path),
                "-",
            ]
        raise RuntimeError(
            "No implementation command configured. Install codex or copilot, or set IMPLEMENTATION_DAEMON_COMMAND."
        )

    def _build_implementation_prompt(self, task: PortalTask, attempt: int) -> str:
        playwright_port = self._implementation_playwright_port(task, attempt)
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
- Playwright port: {playwright_port}
- Acceptance: {task.acceptance or "none listed"}

Primary plan document:
- docs/AI_AGENT_CHAT_IMPLEMENTATION_PLAN.md when the task ID starts with AGENT-
- docs/211_SERVICE_NAVIGATION_PORTAL_PLAN.md when the task ID starts with PORTAL-

Rules:
- Read the relevant plan and nearby code before editing.
- Do not revert unrelated local changes.
- Prefer existing repo patterns and small, reviewable changes.
- Implement the expected outputs for this task.
- Use PLAYWRIGHT_PORT={playwright_port} for Playwright, Vite preview, smoke, visual, and full-stack UI validation; the daemon validates with the same environment.
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
    parser.add_argument(
        "--until-complete",
        action="store_true",
        help="Run backlog passes until every parsed task is completed, then exit",
    )
    parser.add_argument(
        "--max-passes",
        type=int,
        default=0,
        help="Maximum backlog passes before exiting; 0 disables the limit",
    )
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
    parser.add_argument(
        "--allowed-tracks",
        action="append",
        default=[],
        help="Comma-separated task tracks this daemon may select; repeatable. Defaults to all tracks.",
    )
    parser.add_argument(
        "--allowed-task-ids",
        action="append",
        default=[],
        help="Comma-separated task IDs this daemon may select; repeatable. Defaults to all task IDs.",
    )
    parser.add_argument("--implement", action="store_true", help="Invoke an autonomous implementation agent for the ready task")
    parser.add_argument(
        "--implementation-command",
        default="",
        help="Command used for implementation. Defaults to codex exec with local Copilot CLI fallback when available.",
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
        allowed_tracks=args.allowed_tracks,
        allowed_task_ids=args.allowed_task_ids,
    )
    passes = 0
    while True:
        result = daemon.run_once()
        passes += 1
        logger.info("Portal implementation daemon pass complete: %s", result)
        if args.until_complete and int(result.get("completed_count") or 0) >= int(result.get("task_count") or 0):
            logger.info("Portal implementation daemon backlog complete after %s pass(es)", passes)
            break
        if args.once:
            break
        if args.max_passes > 0 and passes >= args.max_passes:
            logger.info("Portal implementation daemon reached max passes: %s", args.max_passes)
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
