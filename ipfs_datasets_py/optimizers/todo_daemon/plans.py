"""Reusable markdown todo-plan parsing helpers for optimizer daemons."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


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
