"""Reusable markdown task-board status helpers for todo daemons."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any, Callable, Optional

from .engine import Task, utc_now
from .plans import CHECKBOX_TASK_RE


NowFactory = Callable[[], str]


def truncate_text(text: str, *, limit: Optional[int]) -> str:
    """Return ``text`` truncated with the standard todo-daemon marker."""

    if limit is not None and len(text) > limit:
        return text[:limit] + "\n\n[truncated]\n"
    return text


def _task_checkbox_index(selected_task: Any) -> int:
    task_id = str(getattr(selected_task, "task_id", "") or "")
    if task_id.startswith("checkbox-"):
        try:
            return int(task_id.removeprefix("checkbox-"))
        except ValueError:
            return -1
    try:
        return int(getattr(selected_task, "checkbox_id"))
    except (TypeError, ValueError):
        return -1


def focused_task_board_excerpt(markdown: str, selected_task: Any, *, limit: int) -> str:
    """Return a compact task-board excerpt centered on ``selected_task``."""

    if limit <= 0 or len(markdown) <= limit:
        return markdown
    if selected_task is None:
        return truncate_text(markdown, limit=limit)

    lines = markdown.splitlines(keepends=True)
    target_line_index: Optional[int] = None
    target_checkbox_index = _task_checkbox_index(selected_task)
    if target_checkbox_index > 0:
        current_checkbox_index = 0
        for index, line in enumerate(lines):
            if CHECKBOX_TASK_RE.match(line.rstrip("\n")):
                current_checkbox_index += 1
                if current_checkbox_index == target_checkbox_index:
                    target_line_index = index
                    break

    if target_line_index is None:
        needle = str(getattr(selected_task, "title", "") or "").strip()
        for index, line in enumerate(lines):
            if needle and needle in line:
                target_line_index = index
                break

    if target_line_index is None:
        return truncate_text(markdown, limit=limit)

    header = "[task-board excerpt centered on daemon-selected task]\n"
    footer = "\n[task-board excerpt truncated around selected task]\n"
    available = max(0, limit - len(header) - len(footer))
    start = target_line_index
    end = target_line_index + 1
    excerpt = lines[target_line_index]

    while len(excerpt) < available and (start > 0 or end < len(lines)):
        grew = False
        if start > 0 and len(excerpt) + len(lines[start - 1]) <= available:
            start -= 1
            excerpt = lines[start] + excerpt
            grew = True
        if end < len(lines) and len(excerpt) + len(lines[end]) <= available:
            excerpt += lines[end]
            end += 1
            grew = True
        if not grew:
            break

    return header + excerpt + footer


def managed_status_block_pattern(start_marker: str, end_marker: str) -> re.Pattern[str]:
    """Return a regex matching a daemon-managed generated-status block."""

    return re.compile(
        r"\n?"
        + re.escape(start_marker)
        + r"[\s\S]*?"
        + re.escape(end_marker)
        + r"\n?",
        re.MULTILINE,
    )


def task_status_counts(tasks: Iterable[Task]) -> dict[str, int]:
    """Return normalized task counts for a task board."""

    task_list = list(tasks)
    return {
        "needed": sum(1 for task in task_list if task.status == "needed"),
        "in_progress": sum(1 for task in task_list if task.status == "in-progress"),
        "complete": sum(1 for task in task_list if task.status == "complete"),
        "blocked": sum(1 for task in task_list if task.status == "blocked"),
    }


def count_unmanaged_generated_status_sections(
    markdown: str,
    *,
    start_marker: str,
    end_marker: str,
    heading: str = "## Generated Status",
) -> int:
    """Count generated-status headings outside a daemon-managed marker block."""

    count = 0
    in_managed_block = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped == start_marker:
            in_managed_block = True
            continue
        if stripped == end_marker:
            in_managed_block = False
            continue
        if not in_managed_block and stripped == heading:
            count += 1
    return count


def strip_unmanaged_generated_status_sections(
    markdown: str,
    *,
    start_marker: str,
    end_marker: str,
    heading: str = "## Generated Status",
) -> str:
    """Remove stale generated-status sections outside a daemon-managed block."""

    lines = markdown.splitlines()
    cleaned: list[str] = []
    in_managed_block = False
    skipping_unmanaged_status = False
    for line in lines:
        stripped = line.strip()
        if stripped == start_marker:
            in_managed_block = True
            skipping_unmanaged_status = False
            cleaned.append(line)
            continue
        if stripped == end_marker:
            in_managed_block = False
            cleaned.append(line)
            continue
        if skipping_unmanaged_status:
            if stripped.startswith("## ") or stripped == start_marker:
                skipping_unmanaged_status = False
            else:
                continue
        if not in_managed_block and stripped == heading:
            skipping_unmanaged_status = True
            continue
        cleaned.append(line)
    return "\n".join(cleaned).rstrip() + ("\n" if markdown.endswith("\n") else "")


def generated_status_block(
    *,
    latest: Mapping[str, Any],
    tasks: Iterable[Task],
    start_marker: str,
    end_marker: str,
    heading: str = "## Generated Status",
    now: NowFactory = utc_now,
) -> str:
    """Build a daemon-managed generated-status markdown block."""

    counts = task_status_counts(tasks)
    return f"""
{start_marker}
{heading}

Last updated: {now()}

- Latest target: `{latest.get("target_task", "")}`
- Latest result: `{latest.get("result", "")}`
- Latest summary: {latest.get("summary", "")}
- Counts: `{json.dumps(counts, sort_keys=True)}`

{end_marker}
"""


def update_generated_status_block(
    markdown: str,
    *,
    latest: Mapping[str, Any],
    tasks: Iterable[Task],
    start_marker: str,
    end_marker: str,
    heading: str = "## Generated Status",
    now: NowFactory = utc_now,
) -> str:
    """Replace or append a daemon-managed generated-status markdown block."""

    markdown = strip_unmanaged_generated_status_sections(
        markdown,
        start_marker=start_marker,
        end_marker=end_marker,
        heading=heading,
    )
    block = generated_status_block(
        latest=latest,
        tasks=tasks,
        start_marker=start_marker,
        end_marker=end_marker,
        heading=heading,
        now=now,
    )
    pattern = managed_status_block_pattern(start_marker, end_marker)
    if pattern.search(markdown):
        return pattern.sub("\n" + block.strip() + "\n", markdown).rstrip() + "\n"
    return markdown.rstrip() + "\n\n" + block
