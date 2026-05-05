"""Reusable diagnostic and failure-loop helpers for todo daemons."""

from __future__ import annotations

import re
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class FailureBlockDecision:
    """Reusable pre-work block decision for repeated stuck task failures."""

    summary: str
    failure_kind: str
    result: str


@dataclass(frozen=True)
class FailureBlockRule:
    """One repeated-failure circuit-breaker rule."""

    failure_kind: str
    count: int
    threshold: int
    summary: str
    result: str


def exception_diagnostic(exc: BaseException, *, limit: int = 5000) -> str:
    """Return a compact traceback suitable for durable daemon diagnostics."""

    return compact_message(
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        limit=limit,
    )


def first_failure_block_decision(
    rules: Sequence[FailureBlockRule],
) -> FailureBlockDecision | None:
    """Return the first block decision whose count reaches its threshold."""

    for rule in rules:
        if int(rule.count) >= max(1, int(rule.threshold)):
            return FailureBlockDecision(
                summary=rule.summary,
                failure_kind=rule.failure_kind,
                result=rule.result,
            )
    return None


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


def compact_status_artifact(
    artifact: Mapping[str, Any],
    *,
    classify_failure_kind: Callable[[Mapping[str, Any]], str] | None = None,
    max_errors: int = 5,
) -> dict[str, Any]:
    """Return a compact artifact payload suitable for daemon status JSON."""

    errors = artifact.get("errors", [])
    return {
        "summary": artifact.get("summary", ""),
        "target_task": artifact.get("target_task", ""),
        "impact": artifact.get("impact", ""),
        "valid_changed_files": artifact.get("changed_files", []),
        "errors": errors[:max_errors] if isinstance(errors, list) else errors,
        "failure_kind": classify_failure_kind(artifact) if classify_failure_kind else str(artifact.get("failure_kind") or ""),
        "validation_passed": artifact.get("validation_passed", False),
    }


def file_edits_by_path(edits: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Return complete file-edit content keyed by normalized proposal path."""

    return {
        str(edit.get("path") or ""): str(edit.get("content") or "")
        for edit in edits
        if str(edit.get("path") or "")
    }


def match_diagnostic_edit_path(
    diagnostic_path: str,
    edits_by_path: Mapping[str, str],
) -> str | None:
    """Match a compiler diagnostic path to one proposed edit path."""

    normalized = diagnostic_path.replace("\\", "/")
    for edit_path in edits_by_path:
        candidate = edit_path.replace("\\", "/")
        if normalized.endswith(candidate) or candidate.endswith(normalized):
            return edit_path
        basename = candidate.rsplit("/", 1)[-1]
        if basename and normalized.endswith(basename):
            return edit_path
    return None


def render_typescript_diagnostic_context(
    text: str,
    edits_by_path: Mapping[str, str],
    *,
    radius: int = 2,
    limit: int = 6000,
) -> str:
    """Render file-edit snippets around TypeScript diagnostic lines."""

    if not edits_by_path:
        return ""
    snippets: list[str] = []
    seen: set[tuple[str, int]] = set()
    pattern = r"([^\s:()]+\.tsx?)\((\d+),(\d+)\):\s*error\s+(TS\d+):\s*([^\n]+)"
    for match in re.finditer(pattern, text):
        diagnostic_path = match.group(1)
        line_number = int(match.group(2))
        column = int(match.group(3))
        code = match.group(4)
        message = match.group(5).strip()
        edit_path = match_diagnostic_edit_path(diagnostic_path, edits_by_path)
        if edit_path is None or (edit_path, line_number) in seen:
            continue
        seen.add((edit_path, line_number))
        lines = edits_by_path[edit_path].splitlines()
        if not (1 <= line_number <= len(lines)):
            continue
        start = max(1, line_number - radius)
        end = min(len(lines), line_number + radius)
        rendered = [f"{edit_path}:{line_number}:{column} {code}: {message}"]
        for current in range(start, end + 1):
            marker = ">" if current == line_number else " "
            rendered.append(f"{marker} {current}: {lines[current - 1]}")
        snippets.append("\n".join(rendered))
        if sum(len(item) for item in snippets) > limit:
            break
    return "\n\n".join(snippets)[:limit]


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


def format_task_result_failure_context(
    rows: Sequence[ResultRow],
    task_label: str,
    *,
    limit: int = 3,
    empty_message: str = "[No recent failures for selected task.]",
    validation_tail_chars: int = 2000,
) -> str:
    """Format recent failed result rows for one task until the last success."""

    snippets: list[str] = []
    for result, artifact in reversed(rows):
        if not same_task_label(str(artifact.get("target_task") or ""), task_label):
            continue
        if result.get("valid"):
            break
        validation = artifact.get("validation_results", [])
        failures: list[str] = []
        for item in validation if isinstance(validation, list) else []:
            if not isinstance(item, Mapping) or item.get("returncode") in (0, None):
                continue
            command = " ".join(str(part) for part in item.get("command", []))
            stdout = str(item.get("stdout", ""))[-validation_tail_chars:]
            stderr = str(item.get("stderr", ""))[-validation_tail_chars:]
            failures.append(f"{command}\nstdout:\n{stdout}\nstderr:\n{stderr}".strip())
        errors = artifact.get("errors", [])
        if not isinstance(errors, list):
            errors = [errors]
        snippets.append(
            "\n".join(
                part
                for part in [
                    f"Summary: {artifact.get('summary') or '<empty>'}",
                    f"Failure kind: {artifact.get('failure_kind') or 'invalid_no_change'}",
                    f"Errors: {'; '.join(str(error) for error in errors[:3]) or '<none>'}",
                    "Validation failures:\n" + "\n\n".join(failures) if failures else "",
                ]
                if part
            )
        )
        if len(snippets) >= limit:
            break
    return "\n\n---\n\n".join(reversed(snippets)) if snippets else empty_message


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
