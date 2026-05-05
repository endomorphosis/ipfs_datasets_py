"""Reusable result-log and failure-history helpers for todo daemons."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .engine import compact_message


ResultRow = tuple[dict[str, Any], dict[str, Any]]
FailureClassifier = Callable[[Mapping[str, Any]], str]
Compactor = Callable[[Any, int], str]


def read_daemon_results(
    path: Path,
    *,
    results_key: str = "results",
    artifact_key: str = "artifact",
) -> list[ResultRow]:
    """Read JSONL daemon result rows as ``(result, artifact)`` tuples."""

    if not path.exists():
        return []
    rows: list[ResultRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        results = record.get(results_key, []) if isinstance(record, dict) else []
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            artifact = result.get(artifact_key, {})
            if isinstance(artifact, dict):
                rows.append((result, artifact))
    return rows


def normalize_task_label(value: str) -> str:
    """Normalize task labels for stable retry/failure comparisons."""

    normalized = str(value or "").replace("`", "").strip()
    return re.sub(r"\s+", " ", normalized)


def same_task_label(left: str, right: str) -> bool:
    return normalize_task_label(left) == normalize_task_label(right)


def default_failure_classifier(artifact: Mapping[str, Any]) -> str:
    explicit = str(artifact.get("failure_kind") or "")
    return explicit or "invalid_no_change"


def recent_failure_count(
    rows: Sequence[ResultRow],
    task_label: str,
    failure_kind: str,
    *,
    classify_failure_kind: FailureClassifier = default_failure_classifier,
) -> int:
    """Count recent consecutive failures of one kind for a task."""

    count = 0
    for result, artifact in reversed(rows):
        if not same_task_label(str(artifact.get("target_task") or ""), task_label):
            continue
        if result.get("valid"):
            break
        row_failure_kind = classify_failure_kind(artifact)
        if row_failure_kind == failure_kind:
            count += 1
            continue
        break
    return count


def recent_total_failure_count(rows: Sequence[ResultRow], task_label: str) -> int:
    """Count recent consecutive failures for a task regardless of kind."""

    count = 0
    for result, artifact in reversed(rows):
        if not same_task_label(str(artifact.get("target_task") or ""), task_label):
            continue
        if result.get("valid"):
            break
        count += 1
    return count


def current_task_failure_counts(
    rows: Sequence[ResultRow],
    task_label: str,
    *,
    classify_failure_kind: FailureClassifier = default_failure_classifier,
) -> dict[str, Any]:
    """Return failure counts by kind since the task last succeeded."""

    total = 0
    by_kind: dict[str, int] = {}
    for result, artifact in reversed(rows):
        if not same_task_label(str(artifact.get("target_task") or ""), task_label):
            continue
        if result.get("valid"):
            break
        total += 1
        kind = classify_failure_kind(artifact)
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {"total_since_success": total, "by_kind_since_success": by_kind}


def rounds_since_last_valid(rows: Sequence[ResultRow]) -> int:
    """Return consecutive daemon rounds since the most recent valid result."""

    count = 0
    for result, _artifact in reversed(rows):
        if result.get("valid"):
            break
        count += 1
    return count


def last_task_attempt_index(rows: Sequence[ResultRow], task_label: str) -> int:
    """Return the last result index that attempted ``task_label``, or ``-1``."""

    for index in range(len(rows) - 1, -1, -1):
        _result, artifact = rows[index]
        if same_task_label(str(artifact.get("target_task") or ""), task_label):
            return index
    return -1


def task_failure_summary(
    rows: Sequence[ResultRow],
    task_label: str,
    *,
    classify_failure_kind: FailureClassifier = default_failure_classifier,
    compact: Compactor = compact_message,
) -> dict[str, Any]:
    """Return counts and a compact latest-failure summary for one task."""

    counts = current_task_failure_counts(
        rows,
        task_label,
        classify_failure_kind=classify_failure_kind,
    )
    latest_failure: dict[str, Any] = {}
    for result, artifact in reversed(rows):
        if not same_task_label(str(artifact.get("target_task") or ""), task_label):
            continue
        if result.get("valid"):
            break
        errors = artifact.get("errors", [])
        if isinstance(errors, list):
            compact_errors = [compact(error, 240) for error in errors[:3]]
        else:
            compact_errors = [compact(errors, 240)]
        latest_failure = {
            "summary": compact(artifact.get("summary", ""), 240),
            "failure_kind": classify_failure_kind(artifact),
            "errors": compact_errors,
        }
        break
    return {**counts, "latest_failure": latest_failure}
