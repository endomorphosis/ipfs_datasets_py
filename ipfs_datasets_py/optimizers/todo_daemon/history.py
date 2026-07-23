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
SuccessPredicate = Callable[[Mapping[str, Any]], bool]


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


def read_daemon_proposal_records(
    path: Path,
    *,
    proposal_key: str = "proposal",
    diagnostic_key: str = "diagnostic",
    include_diagnostics: bool = False,
    stage_key: str = "stage",
    diagnostic_stage_key: str = "_diagnostic_stage",
) -> list[dict[str, Any]]:
    """Read JSONL runner rows that store proposal and optional diagnostic objects."""

    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        proposal = record.get(proposal_key)
        diagnostic = record.get(diagnostic_key)
        if isinstance(proposal, dict):
            rows.append(proposal)
        elif include_diagnostics and isinstance(diagnostic, dict):
            row = dict(diagnostic)
            row[diagnostic_stage_key] = record.get(stage_key, "")
            rows.append(row)
    return rows


def proposal_record_succeeded(record: Mapping[str, Any]) -> bool:
    """Return whether a proposal-style record represents a successful applied change."""

    return bool(record.get("applied") and record.get("validation_passed") and not record.get("errors"))


def recent_proposal_failures(
    records: Sequence[Mapping[str, Any]],
    task_label: str,
    *,
    limit: int = 3,
    task_key: str = "target_task",
    succeeded: SuccessPredicate = proposal_record_succeeded,
    normalize_task_labels: bool = True,
) -> list[dict[str, Any]]:
    """Return recent same-task proposal records since the last successful record."""

    failures: list[dict[str, Any]] = []
    for record in reversed(records):
        record_task = str(record.get(task_key) or "")
        matches = (
            same_task_label(record_task, task_label)
            if normalize_task_labels
            else record_task == task_label
        )
        if not matches:
            continue
        if succeeded(record):
            break
        failures.append(dict(record))
        if len(failures) >= limit:
            break
    return failures


def should_use_compact_prompt_for_failures(
    failures: Sequence[Mapping[str, Any]],
    *,
    retry_failure_kinds: set[str] | frozenset[str] = frozenset({"parse", "llm"}),
    threshold: int = 2,
) -> bool:
    """Return whether repeated proposal failures should switch to compact prompts."""

    count = 0
    for failure in failures:
        if str(failure.get("failure_kind") or "") in retry_failure_kinds:
            count += 1
    return count >= threshold


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
