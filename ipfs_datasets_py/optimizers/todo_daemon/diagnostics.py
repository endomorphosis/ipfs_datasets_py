"""Reusable diagnostic and failure-loop helpers for todo daemons."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any, Mapping

from .history import FailureClassifier, ResultRow, same_task_label


SignatureExtractor = Callable[[str], Sequence[str]]
ValidationTextExtractor = Callable[[Mapping[str, Any]], str]


def artifact_validation_text(artifact: Mapping[str, Any]) -> str:
    """Collect artifact errors and validation output into one diagnostic string."""

    parts: list[str] = []
    errors = artifact.get("errors", [])
    if isinstance(errors, list):
        parts.extend(str(error) for error in errors if error)
    elif errors:
        parts.append(str(errors))

    validation = artifact.get("validation_results", [])
    if isinstance(validation, list):
        for item in validation:
            if isinstance(item, Mapping):
                parts.append(str(item.get("stdout") or ""))
                parts.append(str(item.get("stderr") or ""))
    return "\n".join(parts)


def has_diagnostic_codes(text: str, codes: set[str] | frozenset[str]) -> bool:
    """Return whether ``text`` contains any daemon-specific diagnostic code."""

    if not text:
        return False
    return any(code in text for code in codes)


def diagnostic_signatures(text: str, *, max_message_chars: int = 120) -> list[str]:
    """Return stable ``CODE:message`` signatures for repeated compiler failures."""

    signatures: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"error\s+([A-Z]+\d+):\s*([^\n]+)", text):
        code = match.group(1)
        message = re.sub(r"'[^']+'", "'<symbol>'", match.group(2).strip())
        message = re.sub(r"\s+", " ", message)
        signature = f"{code}:{message[:max_message_chars]}"
        if signature not in seen:
            seen.add(signature)
            signatures.append(signature)
    return signatures


def quality_failure_counts(
    rows: Sequence[ResultRow],
    *,
    classify_failure_kind: FailureClassifier,
    quality_failure_kind: str,
    signature_extractor: SignatureExtractor = diagnostic_signatures,
    validation_text_extractor: ValidationTextExtractor = artifact_validation_text,
) -> dict[str, Any]:
    """Summarize no-change quality failures by total, task, and signature."""

    total = 0
    consecutive = 0
    by_task: dict[str, int] = {}
    by_signature: dict[str, int] = {}
    for result, artifact in rows:
        if result.get("valid") or artifact.get("changed_files"):
            continue
        if classify_failure_kind(artifact) != quality_failure_kind:
            continue
        total += 1
        task = str(artifact.get("target_task") or "")
        if task:
            by_task[task] = by_task.get(task, 0) + 1
        for signature in signature_extractor(validation_text_extractor(artifact)):
            key = f"{task} :: {signature}" if task else signature
            by_signature[key] = by_signature.get(key, 0) + 1

    for result, artifact in reversed(rows):
        if result.get("valid"):
            break
        if artifact.get("changed_files") or classify_failure_kind(artifact) != quality_failure_kind:
            break
        consecutive += 1

    return {
        "total": total,
        "consecutive": consecutive,
        "by_task": by_task,
        "by_signature": by_signature,
        "top_signature": max(by_signature.items(), key=lambda item: item[1])[0] if by_signature else "",
        "top_signature_count": max(by_signature.values()) if by_signature else 0,
    }


def rollback_failure_counts(
    rows: Sequence[ResultRow],
    *,
    classify_failure_kind: FailureClassifier,
    rollback_failure_kinds: set[str] | frozenset[str],
) -> dict[str, Any]:
    """Summarize no-change failures that should count toward rollback recovery."""

    total = 0
    consecutive = 0
    by_task: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for result, artifact in rows:
        if result.get("valid") or artifact.get("changed_files"):
            continue
        kind = classify_failure_kind(artifact)
        if kind not in rollback_failure_kinds:
            continue
        total += 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        task = str(artifact.get("target_task") or "")
        if task:
            by_task[task] = by_task.get(task, 0) + 1

    for result, artifact in reversed(rows):
        if result.get("valid"):
            break
        if artifact.get("changed_files") or classify_failure_kind(artifact) not in rollback_failure_kinds:
            break
        consecutive += 1

    return {
        "total": total,
        "consecutive": consecutive,
        "by_task": by_task,
        "by_kind": by_kind,
    }


def recent_rollback_failure_count(
    rows: Sequence[ResultRow],
    task_label: str,
    *,
    classify_failure_kind: FailureClassifier,
    rollback_failure_kinds: set[str] | frozenset[str],
) -> int:
    """Count recent same-task failures that did not change files and need rollback handling."""

    count = 0
    for result, artifact in reversed(rows):
        if not same_task_label(str(artifact.get("target_task") or ""), task_label):
            continue
        if result.get("valid"):
            break
        if artifact.get("changed_files"):
            break
        if classify_failure_kind(artifact) not in rollback_failure_kinds:
            break
        count += 1
    return count
