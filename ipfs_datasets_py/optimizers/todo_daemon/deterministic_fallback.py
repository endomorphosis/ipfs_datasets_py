"""Reusable deterministic fallback helpers for todo daemons."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .engine import Proposal, Task, utc_now


FallbackTitleRules = Sequence[tuple[str, str]]


def fallback_kind_for_task(task: Task, rules: FallbackTitleRules) -> str:
    """Return the fallback kind for a task title, or ``""`` when none match."""

    lowered = task.title.lower()
    for marker, kind in rules:
        if marker.lower() in lowered:
            return kind
    return ""


def task_has_deterministic_fallback(task: Task, rules: FallbackTitleRules) -> bool:
    """Return whether ``task`` matches a deterministic fallback rule."""

    return bool(fallback_kind_for_task(task, rules))


def open_task_has_deterministic_fallback(
    tasks: Iterable[Task],
    rules: FallbackTitleRules,
    *,
    open_statuses: set[str] | frozenset[str] = frozenset({"needed", "in-progress"}),
) -> bool:
    """Return whether any open task has a deterministic fallback rule."""

    return any(task.status in open_statuses and task_has_deterministic_fallback(task, rules) for task in tasks)


def load_deterministic_progress_manifest(
    path: Path,
    *,
    strategy: str,
    schema_version: int = 1,
    now: Any = utc_now,
) -> dict[str, Any]:
    """Load or initialize a deterministic-fallback progress manifest."""

    if path.exists():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                parsed.setdefault("schemaVersion", schema_version)
                parsed.setdefault("records", [])
                parsed.setdefault("strategy", strategy)
                return parsed
        except json.JSONDecodeError:
            pass
    return {
        "schemaVersion": schema_version,
        "strategy": strategy,
        "updatedAt": now(),
        "records": [],
    }


def tranche_number_from_title(title: str, *, pattern: str = r"\btranche\s+(\d+)\b") -> int | None:
    """Extract a tranche number from a task title when present."""

    match = re.search(pattern, title.lower())
    return int(match.group(1)) if match else None


def build_deterministic_progress_record(
    task: Task,
    fallback_kind: str,
    *,
    source_evidence_ids: Sequence[str] = (),
    artifact_contracts: Sequence[str] = (),
    guardrails: Sequence[str] = (),
    blocked_actions: Sequence[str] = (),
    runtime_policy: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
    now: Any = utc_now,
) -> dict[str, Any]:
    """Build the standard deterministic-fallback progress record."""

    record: dict[str, Any] = {
        "checkboxId": task.checkbox_id,
        "taskLabel": task.label,
        "title": task.title,
        "fallbackKind": fallback_kind,
        "tranche": tranche_number_from_title(task.title),
        "completedAt": now(),
        "sourceEvidenceIds": list(source_evidence_ids),
        "artifactContracts": list(artifact_contracts),
        "guardrails": list(guardrails),
        "blockedActions": list(blocked_actions),
        "runtimePolicy": dict(runtime_policy or {}),
    }
    if extra:
        record.update(dict(extra))
    return record


def upsert_deterministic_progress_record(
    manifest: Mapping[str, Any],
    task: Task,
    record: Mapping[str, Any],
    *,
    now: Any = utc_now,
) -> dict[str, Any]:
    """Return a manifest with ``record`` replacing any prior record for ``task``."""

    updated = dict(manifest)
    records = [item for item in updated.get("records", []) if isinstance(item, dict)]
    records = [
        item
        for item in records
        if str(item.get("taskLabel") or "") != task.label
        and _record_checkbox_id(item) != task.checkbox_id
    ]
    records.append(dict(record))
    updated["records"] = sorted(records, key=lambda item: int(item.get("checkboxId", 0)))
    updated["updatedAt"] = now()
    return updated


def _record_checkbox_id(record: Mapping[str, Any]) -> int:
    try:
        return int(record.get("checkboxId", -1))
    except (TypeError, ValueError):
        return -1


def build_deterministic_replacement_proposal(
    *,
    selected: Task,
    fallback_kind: str,
    manifest: Mapping[str, Any],
    progress_path: Path,
    source_files: Sequence[tuple[str, str]],
    validation_commands: Sequence[Sequence[str]],
    summary: str | None = None,
    impact: str = "",
    trusted_validation_commands: bool = True,
    requires_visible_source_change: bool = True,
) -> Proposal:
    """Build a trusted complete-file replacement proposal for deterministic fallback."""

    files = [{"path": path, "content": content} for path, content in source_files]
    files.append(
        {
            "path": progress_path.as_posix(),
            "content": json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n",
        }
    )
    return Proposal(
        summary=summary or f"Complete {fallback_kind.replace('_', ' ')} with deterministic fallback.",
        impact=impact,
        files=files,
        validation_commands=[list(command) for command in validation_commands],
        failure_kind="",
        target_task=selected.label,
        trusted_validation_commands=trusted_validation_commands,
        requires_visible_source_change=requires_visible_source_change,
    )
