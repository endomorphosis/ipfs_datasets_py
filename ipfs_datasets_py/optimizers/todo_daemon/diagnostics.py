"""Reusable diagnostic and failure-loop helpers for todo daemons."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any, Mapping

from .engine import Proposal, compact_message
from .history import FailureClassifier, ResultRow, same_task_label


SignatureExtractor = Callable[[str], Sequence[str]]
ValidationTextExtractor = Callable[[Mapping[str, Any]], str]

DEFAULT_RETRY_FAILURE_KINDS = frozenset({"llm", "parse", "empty_proposal"})
DEFAULT_RETRY_ERROR_MARKERS = frozenset(
    {
        "cloudflare",
        "403 forbidden",
        "timed out",
        "timeout",
        "could not generate",
        "provider",
    }
)
DEFAULT_SKIP_VALIDATION_FAILURE_KINDS = frozenset({"llm", "parse", "empty_proposal"})


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


def proposal_error_text(proposal: Proposal | Mapping[str, Any]) -> str:
    """Return a lower-case text blob from proposal errors for marker checks."""

    errors = proposal.errors if isinstance(proposal, Proposal) else proposal.get("errors", [])
    if isinstance(errors, list):
        return " ".join(str(error).lower() for error in errors)
    return str(errors or "").lower()


def is_retryable_proposal_failure(
    proposal: Proposal | Mapping[str, Any],
    *,
    retry_failure_kinds: set[str] | frozenset[str] = DEFAULT_RETRY_FAILURE_KINDS,
    retry_error_markers: set[str] | frozenset[str] = DEFAULT_RETRY_ERROR_MARKERS,
) -> bool:
    """Return whether a proposal failure should leave the task available for retry."""

    failure_kind = (
        proposal.failure_kind
        if isinstance(proposal, Proposal)
        else str(proposal.get("failure_kind") or "")
    )
    if failure_kind in retry_failure_kinds:
        return True
    text = proposal_error_text(proposal)
    return bool(text and any(marker in text for marker in retry_error_markers))


def should_skip_validation_for_empty_proposal(
    proposal: Proposal | Mapping[str, Any],
    *,
    skip_failure_kinds: set[str] | frozenset[str] = DEFAULT_SKIP_VALIDATION_FAILURE_KINDS,
) -> bool:
    """Return whether validation can be skipped because no candidate files exist."""

    files = proposal.files if isinstance(proposal, Proposal) else proposal.get("files", [])
    if files:
        return False
    failure_kind = (
        proposal.failure_kind
        if isinstance(proposal, Proposal)
        else str(proposal.get("failure_kind") or "")
    )
    return failure_kind in skip_failure_kinds


def block_threshold_for_failure_kind(
    failure_kind: str,
    *,
    default_threshold: int,
    capped_failure_kinds: set[str] | frozenset[str] = frozenset(),
    capped_threshold: int = 2,
    exact_thresholds: Mapping[str, int] | None = None,
) -> int:
    """Return a retry block threshold for a failure kind."""

    thresholds = exact_thresholds or {}
    if failure_kind in thresholds:
        return max(1, int(thresholds[failure_kind]))
    if failure_kind in capped_failure_kinds:
        return max(1, min(int(default_threshold), int(capped_threshold)))
    return max(1, int(default_threshold))


def proposal_block_threshold(
    proposal: Proposal | Mapping[str, Any],
    *,
    default_threshold: int,
    capped_failure_kinds: set[str] | frozenset[str] = frozenset(),
    capped_threshold: int = 2,
    exact_thresholds: Mapping[str, int] | None = None,
) -> int:
    """Return a retry block threshold for a proposal-like failure record."""

    failure_kind = (
        proposal.failure_kind
        if isinstance(proposal, Proposal)
        else str(proposal.get("failure_kind") or "")
    )
    return block_threshold_for_failure_kind(
        failure_kind,
        default_threshold=default_threshold,
        capped_failure_kinds=capped_failure_kinds,
        capped_threshold=capped_threshold,
        exact_thresholds=exact_thresholds,
    )


def prompt_limit_for_mode(
    *,
    max_prompt_chars: int,
    max_compact_prompt_chars: int,
    compact_prompt: bool,
) -> int:
    """Return the active prompt limit for full or compact prompt mode."""

    if compact_prompt:
        return min(int(max_prompt_chars), int(max_compact_prompt_chars))
    return int(max_prompt_chars)


def proposal_record_has_failure_markers(
    record: Mapping[str, Any],
    *,
    failure_kind: str,
    markers: set[str] | frozenset[str],
) -> bool:
    """Return whether a proposal record has one failure kind and any error marker."""

    if str(record.get("failure_kind") or "") != failure_kind:
        return False
    text = proposal_error_text(record)
    return bool(text and any(marker in text for marker in markers))


def count_recent_proposal_failures(
    failures: Sequence[Mapping[str, Any]],
    *,
    failure_kinds: set[str] | frozenset[str] | None = None,
) -> int:
    """Count recent proposal failures, optionally restricted to failure kinds."""

    count = 0
    for failure in failures:
        kind = str(failure.get("failure_kind") or "")
        if failure_kinds is None or kind in failure_kinds:
            count += 1
    return count


def count_proposal_records_with_failure_markers(
    records: Sequence[Mapping[str, Any]],
    *,
    failure_kind: str,
    markers: set[str] | frozenset[str],
) -> int:
    """Count proposal records matching one failure kind and at least one error marker."""

    return sum(
        1
        for record in records
        if proposal_record_has_failure_markers(
            record,
            failure_kind=failure_kind,
            markers=markers,
        )
    )


FailureContextGuidance = Callable[[Sequence[Mapping[str, Any]]], Sequence[str]]


def format_recent_failure_context(
    failures: Sequence[Mapping[str, Any]],
    *,
    empty_message: str = "No recent failures for this task.",
    guidance: FailureContextGuidance | None = None,
    summary_limit: int = 300,
    error_limit: int = 300,
    validation_output_limit: int = 900,
) -> str:
    """Format recent proposal failures for a compact LLM repair prompt."""

    if not failures:
        return empty_message
    parts: list[str] = []
    for index, failure in enumerate(failures, start=1):
        validation_bits: list[str] = []
        for result in failure.get("validation_results", []) or []:
            if not isinstance(result, Mapping) or int(result.get("returncode", 0)) == 0:
                continue
            command = " ".join(str(part) for part in result.get("command", []))
            output = str(result.get("stdout", "")) + " " + str(result.get("stderr", ""))
            validation_bits.append(
                f"{command}: {compact_message(output, limit=validation_output_limit)}"
            )
        errors = failure.get("errors", []) or []
        if not isinstance(errors, list):
            errors = [errors]
        parts.append(
            "\n".join(
                [
                    f"Failure {index}: kind={failure.get('failure_kind', '')}",
                    f"summary={compact_message(failure.get('summary', ''), limit=summary_limit)}",
                    f"errors={'; '.join(compact_message(error, limit=error_limit) for error in errors[:3])}",
                    f"validation={'; '.join(validation_bits) if validation_bits else '<none>'}",
                ]
            )
        )
    if guidance is not None:
        parts.extend(str(item) for item in guidance(failures) if item)
    return "\n\n".join(parts)


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
