"""Reusable markdown todo-plan parsing helpers for optimizer daemons."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple


TASK_HEADING_RE = re.compile(r"^### Task\s+([^:\n]+):\s+(.+)$", re.MULTILINE)
CHECKBOX_TASK_RE = re.compile(r"^(?P<indent>\s*)-\s+\[(?P<mark>[ xX~!])\]\s+(?P<title>.+)$", re.MULTILINE)
DAEMON_TASK_BOARD_RE = re.compile(
    r"\n?<!--\s*[\w.-]+-daemon-task-board:start\s*-->[\s\S]*?<!--\s*[\w.-]+-daemon-task-board:end\s*-->\n?",
    re.MULTILINE,
)


@dataclass(frozen=True)
class PlanTask:
    """Task extracted from a markdown implementation or todo plan."""

    task_id: str
    title: str
    status: str

    @property
    def label(self) -> str:
        return f"Task {self.task_id}: {self.title}"


def strip_daemon_task_board(text: str) -> str:
    """Remove a generated daemon task board from a markdown plan."""

    return DAEMON_TASK_BOARD_RE.sub("\n", text).rstrip() + "\n"


def status_from_task_block(block: str) -> str:
    """Infer a normalized task status from a heading-style task block."""

    status_match = re.search(r"^Status:\s*(.+)$", block, re.MULTILINE)
    if not status_match:
        return "needed"
    status = status_match.group(1).strip().lower()
    if "implemented" in status and "partially" not in status:
        return "complete"
    if "partial" in status or "in progress" in status:
        return "in-progress"
    if "blocked" in status:
        return "blocked"
    return "needed"


def status_from_checkbox(mark: str) -> str:
    """Normalize a markdown checkbox mark into a daemon task status."""

    if mark.lower() == "x":
        return "complete"
    if mark == "~":
        return "in-progress"
    if mark == "!":
        return "blocked"
    return "needed"


def clean_checkbox_title(title: str) -> str:
    """Remove trailing generated comments from a checkbox title."""

    return re.sub(r"\s+<!--.*?-->\s*$", "", title).strip()


def extract_plan_tasks(markdown: str) -> List[PlanTask]:
    """Extract ordered tasks from heading-style or checkbox-style markdown."""

    text = strip_daemon_task_board(markdown)
    matches = list(TASK_HEADING_RE.finditer(text))
    tasks: List[PlanTask] = []
    for index, match in enumerate(matches):
        block_start = match.end()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[block_start:block_end]
        tasks.append(
            PlanTask(
                task_id=match.group(1).strip(),
                title=match.group(2).strip(),
                status=status_from_task_block(block),
            )
        )
    if tasks:
        return tasks

    for index, match in enumerate(CHECKBOX_TASK_RE.finditer(text), start=1):
        title = clean_checkbox_title(match.group("title"))
        if not title:
            continue
        tasks.append(
            PlanTask(
                task_id=f"checkbox-{index}",
                title=title,
                status=status_from_checkbox(match.group("mark")),
            )
        )
    return tasks


def replace_checkbox_mark(markdown: str, task: PlanTask, mark: str) -> str:
    """Replace the markdown checkbox mark for a parsed checkbox task."""

    if not task.task_id.startswith("checkbox-"):
        return markdown
    try:
        target_index = int(task.task_id.removeprefix("checkbox-"))
    except ValueError:
        return markdown

    current_index = 0
    lines = markdown.splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = CHECKBOX_TASK_RE.match(line.rstrip("\n"))
        if not match:
            continue
        current_index += 1
        if current_index == target_index:
            lines[index] = re.sub(r"^(\s*-\s+\[)[ xX~!](\]\s+)", rf"\g<1>{mark}\2", line, count=1)
            break
    return "".join(lines)


def markdown_task_label(task: Optional[PlanTask]) -> str:
    """Return a task label safe to embed inside markdown backticks."""

    return task.label.replace("`", "'") if task else "none"


def plan_task_from_latest_result(
    tasks: Sequence[PlanTask],
    latest: Mapping[str, Any],
) -> Optional[PlanTask]:
    """Resolve a daemon result's target task back to a parsed plan task."""

    artifact = latest.get("artifact", {}) if isinstance(latest.get("artifact"), Mapping) else {}
    target_label = str(artifact.get("target_task") or "").replace("`", "'").strip()
    if not target_label:
        return None
    for task in tasks:
        if markdown_task_label(task) == target_label or task.label == target_label:
            return task
    id_match = re.search(r"Task\s+([^:\s]+):", target_label)
    if id_match:
        task_id = id_match.group(1)
        for task in tasks:
            if task.task_id == task_id:
                return task
    return None


FailureSummaryFn = Callable[[Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]], str], Mapping[str, Any]]
FailureBudgetFn = Callable[[PlanTask, Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]]], bool]
TaskDependencyReasonFn = Callable[[PlanTask, Sequence[PlanTask]], str]
TaskFailureCountFn = Callable[[Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]], str], int]


def build_blocked_task_backlog(
    tasks: Sequence[PlanTask],
    rows: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    failure_summary_fn: FailureSummaryFn,
    failure_budget_exhausted_fn: FailureBudgetFn,
    limit: int,
) -> list[dict[str, Any]]:
    """Return reusable blocked-task backlog records with failure summaries."""

    max_items = max(0, int(limit))
    if max_items <= 0:
        return []
    backlog: list[dict[str, Any]] = []
    for task in tasks:
        if task.status != "blocked":
            continue
        summary = failure_summary_fn(rows, task.label)
        backlog.append(
            {
                "task": task.label,
                "task_id": task.task_id,
                "title": task.title,
                "total_failures_since_success": summary.get("total_since_success", 0),
                "failure_kinds_since_success": summary.get("by_kind_since_success", {}),
                "latest_failure": summary.get("latest_failure", {}),
                "failure_budget_exhausted": failure_budget_exhausted_fn(task, rows),
            }
        )
        if len(backlog) >= max_items:
            break
    return backlog


def blocked_task_backlog_markdown(
    backlog: Sequence[Mapping[str, Any]],
    *,
    empty_message: str = "[No blocked tasks in the current daemon backlog.]",
) -> str:
    """Render blocked-task backlog records as compact markdown."""

    if not backlog:
        return empty_message
    lines: list[str] = []
    for item in backlog:
        latest = item.get("latest_failure", {}) if isinstance(item.get("latest_failure"), Mapping) else {}
        errors = latest.get("errors", []) if isinstance(latest.get("errors", []), list) else []
        task_label = str(item.get("task", "")).replace("`", "'")
        lines.append(f"- `{task_label}`")
        lines.append(f"  - failures since success: `{item.get('total_failures_since_success', 0)}`")
        if item.get("failure_budget_exhausted"):
            lines.append("  - autonomous revisit: `skipped; task failure budget exhausted`")
        kinds = item.get("failure_kinds_since_success", {})
        if kinds:
            lines.append(f"  - failure kinds: `{json.dumps(kinds, sort_keys=True)}`")
        if latest:
            lines.append(f"  - latest failure kind: `{latest.get('failure_kind', '')}`")
            if latest.get("summary"):
                lines.append(f"  - latest summary: {latest.get('summary')}")
            if errors:
                lines.append(f"  - latest errors: {'; '.join(str(error) for error in errors[:2])}")
    return "\n".join(lines)


def first_open_plan_task(tasks: Sequence[PlanTask]) -> Optional[PlanTask]:
    """Return the first needed or in-progress plan task."""

    for status in ("needed", "in-progress"):
        for task in tasks:
            if task.status == status:
                return task
    return None


def select_blocked_plan_task(
    tasks: Sequence[PlanTask],
    rows: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    strategy: str = "plan-order",
    dependency_reason_fn: Optional[TaskDependencyReasonFn] = None,
    failure_budget_exhausted_fn: Optional[FailureBudgetFn] = None,
    recent_total_failure_count_fn: Optional[TaskFailureCountFn] = None,
    last_task_attempt_index_fn: Optional[TaskFailureCountFn] = None,
) -> Optional[PlanTask]:
    """Select a blocked task to revisit using a reusable strategy."""

    blocked: list[tuple[int, PlanTask]] = []
    for index, task in enumerate(tasks):
        if task.status != "blocked":
            continue
        if dependency_reason_fn is not None and dependency_reason_fn(task, tasks):
            continue
        if failure_budget_exhausted_fn is not None and failure_budget_exhausted_fn(task, rows):
            continue
        blocked.append((index, task))
    if not blocked:
        return None
    normalized_strategy = str(strategy or "plan-order")
    if normalized_strategy == "plan-order" or not rows:
        return blocked[0][1]
    if recent_total_failure_count_fn is None or last_task_attempt_index_fn is None:
        return blocked[0][1]
    if normalized_strategy == "fewest-failures":
        return min(
            blocked,
            key=lambda item: (
                recent_total_failure_count_fn(rows, item[1].label),
                last_task_attempt_index_fn(rows, item[1].label),
                item[0],
            ),
        )[1]
    if normalized_strategy == "most-failures":
        return min(
            blocked,
            key=lambda item: (
                -recent_total_failure_count_fn(rows, item[1].label),
                last_task_attempt_index_fn(rows, item[1].label),
                item[0],
            ),
        )[1]
    return blocked[0][1]


def select_next_plan_task(
    tasks: Sequence[PlanTask],
    *,
    revisit_blocked: bool = False,
    blocked_selector: Optional[Callable[[Sequence[PlanTask]], Optional[PlanTask]]] = None,
) -> Optional[PlanTask]:
    """Return the next open task, optionally falling back to blocked tasks."""

    open_task = first_open_plan_task(tasks)
    if open_task is not None:
        return open_task
    if revisit_blocked and blocked_selector is not None:
        return blocked_selector(tasks)
    return None
