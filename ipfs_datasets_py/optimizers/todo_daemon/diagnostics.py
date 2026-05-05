"""Reusable diagnostic and failure-loop helpers for todo daemons."""

from __future__ import annotations

import ast
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
DEFAULT_PROVIDER_HTTP_FAILURE_MARKERS = frozenset(
    {
        "cloudflare",
        "403 forbidden",
        "plugins/featured",
        "analytics-events",
    }
)
DEFAULT_TIMEOUT_FAILURE_MARKERS = frozenset({"timed out"})
DEFAULT_PARSE_FAILURE_MARKERS = frozenset({"did not contain json"})
DEFAULT_VALIDATION_FAILURE_MARKERS = frozenset({"ts1005"})


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


def command_output_text(value: Any) -> str:
    """Return subprocess output as text, including timeout byte reprs."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    text = str(value or "")
    stripped = text.strip()
    if len(stripped) >= 3 and stripped[:1].lower() == "b" and stripped[1:2] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            return text
        if isinstance(parsed, bytes):
            return parsed.decode("utf-8", errors="replace")
    return text


def is_pytest_session_noise(text: str) -> bool:
    """Return whether a pytest output line is boilerplate rather than failure signal."""

    return (
        text.startswith("=")
        or text.startswith("platform ")
        or text.startswith("plugins:")
        or text.startswith("rootdir:")
        or text.startswith("configfile:")
        or text.startswith("collected ")
    )


def summarize_test_failure(stdout: Any) -> dict[str, Any]:
    """Summarize failed pytest node ids, exception types, and useful output head."""

    output = command_output_text(stdout)
    failed_tests: list[str] = []
    for match in re.finditer(r"FAILED\s+([^\s]+)", output):
        name = match.group(1).strip()
        if name == "[" or "::" not in name:
            continue
        if name and name not in failed_tests:
            failed_tests.append(name)

    exception_types: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b", output):
        name = match.group(1)
        if name and name not in exception_types:
            exception_types.append(name)

    interesting_lines: list[str] = []
    for line in output.splitlines():
        text = line.strip()
        if not text:
            continue
        if (
            text.startswith("FAILED ")
            or text.startswith("E   ")
            or "Recursion detected" in text
            or "short test summary info" in text
        ):
            interesting_lines.append(text)
        if len(interesting_lines) >= 10:
            break

    return {
        "failed_tests": failed_tests,
        "exception_types": exception_types,
        "failure_head": "\n".join(interesting_lines)[:2000],
    }


def failure_summary_has_content(summary: Mapping[str, Any]) -> bool:
    """Return whether a failure summary contains useful recovery signal."""

    return bool(
        summary.get("failed_tests")
        or summary.get("exception_types")
        or str(summary.get("failure_head") or "").strip()
    )


def summarize_post_apply_validation_failure(validation: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize compile/collection/focused-test validation failures."""

    if not validation or validation.get("valid") is not False:
        return {}

    failed_tests: list[str] = []
    exception_types: list[str] = []
    interesting_lines: list[str] = []
    failure_command: list[str] = []
    for check_name in ("compile", "collect", "focused_tests"):
        check = dict(validation.get(check_name) or {})
        if check.get("valid") is not False:
            continue
        if not failure_command:
            failure_command = [str(part) for part in check.get("command") or []]
        stderr = command_output_text(check.get("stderr") or "")
        stdout = command_output_text(check.get("stdout") or "")
        output_text = stderr + "\n" + stdout
        if check_name == "compile" and "py_compile" not in exception_types:
            exception_types.append("py_compile")
        if "timeout after" in output_text and "TimeoutExpired" not in exception_types:
            exception_types.append("TimeoutExpired")
        for match in re.finditer(r"FAILED\s+([^\s]+)", output_text):
            name = match.group(1).strip()
            if name == "[" or "::" not in name:
                continue
            if name and name not in failed_tests:
                failed_tests.append(name)
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b", output_text):
            name = match.group(1)
            if name and name not in exception_types:
                exception_types.append(name)
        for line in output_text.splitlines():
            text = line.strip()
            if not text or is_pytest_session_noise(text):
                continue
            if (
                text.startswith("File ")
                or text.startswith("E   ")
                or "SyntaxError" in text
                or "IndentationError" in text
                or "timeout after" in text
                or "pytest" in text
                or "FAILED " in text
            ):
                interesting_lines.append(f"{check_name}: {text}")
            if len(interesting_lines) >= 12:
                break

    if not interesting_lines:
        interesting_lines = [str(reason) for reason in validation.get("reasons") or []]

    return {
        "failed_tests": failed_tests[:12],
        "exception_types": exception_types[:8],
        "failure_head": "\n".join(interesting_lines)[:2000],
        "failure_command": failure_command,
    }


def latest_candidate_validation_failure(attempts: Sequence[Any]) -> dict[str, Any]:
    """Return the newest failed candidate preflight from proposal attempts."""

    for item in reversed(list(attempts)):
        if not isinstance(item, Mapping):
            continue
        if item.get("candidate_validation_valid") is not False:
            continue
        summary = dict(item.get("candidate_validation_summary") or {})
        if not failure_summary_has_content(summary):
            retry_reason = str(item.get("retry_reason") or "")
            reasons = [str(reason) for reason in item.get("candidate_validation_reasons") or []]
            summary = {
                "failed_tests": [],
                "exception_types": [
                    match.group(1)
                    for match in re.finditer(
                        r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b",
                        retry_reason + "\n" + "\n".join(reasons),
                    )
                ][:8],
                "failure_head": retry_reason or "; ".join(reasons),
                "failure_command": [],
            }
        return {
            "valid": False,
            "attempt": item.get("attempt"),
            "changed_files": item.get("changed_files", []),
            "reasons": item.get("candidate_validation_reasons", []),
            "summary": summary,
        }
    return {"valid": True, "skipped": True, "reason": "no_failed_candidate_validation"}


def quality_gate_summary(
    *,
    proposal_quality: Mapping[str, Any] | None = None,
    patch_check: Mapping[str, Any] | None = None,
    post_apply_validation: Mapping[str, Any] | None = None,
    tests_result: Mapping[str, Any] | None = None,
    apply_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a stable, non-throwing summary for supervisor recovery code."""

    proposal_quality = proposal_quality or {}
    patch_check = patch_check or {}
    post_apply_validation = post_apply_validation or {}
    tests_result = tests_result or {}
    apply_result = apply_result or {}
    failed_gates: list[str] = []
    if proposal_quality.get("valid") is False:
        failed_gates.append("proposal_quality")
    if patch_check.get("valid") is False:
        failed_gates.append("patch_check")
    if post_apply_validation.get("valid") is False:
        failed_gates.append("post_apply_validation")
    if tests_result.get("valid") is False:
        failed_gates.append("tests")
    if apply_result.get("rolled_back"):
        failed_gates.append(str(apply_result.get("reason") or "rolled_back"))
    return {
        "valid": not failed_gates,
        "failed_gates": failed_gates,
        "proposal_quality_valid": proposal_quality.get("valid"),
        "proposal_quality_reasons": list(proposal_quality.get("reasons") or [])[:8],
        "patch_valid": patch_check.get("valid"),
        "patch_failure_tail": str(patch_check.get("stderr") or "")[-1200:]
        if patch_check.get("valid") is False
        else "",
        "post_apply_validation_valid": post_apply_validation.get("valid"),
        "tests_valid": tests_result.get("valid"),
        "apply_reason": apply_result.get("reason"),
    }


def cycle_quality_gate_summary(cycle_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a cycle quality summary even for legacy records missing the field."""

    synthesized = quality_gate_summary(
        proposal_quality=cycle_payload.get("proposal_quality")
        if isinstance(cycle_payload.get("proposal_quality"), Mapping)
        else {},
        patch_check=cycle_payload.get("patch_check")
        if isinstance(cycle_payload.get("patch_check"), Mapping)
        else {},
        post_apply_validation=cycle_payload.get("post_apply_validation")
        if isinstance(cycle_payload.get("post_apply_validation"), Mapping)
        else {},
        tests_result=cycle_payload.get("tests")
        if isinstance(cycle_payload.get("tests"), Mapping)
        else {},
        apply_result=cycle_payload.get("apply_result")
        if isinstance(cycle_payload.get("apply_result"), Mapping)
        else {},
    )
    existing = cycle_payload.get("quality_gate_summary")
    if isinstance(existing, Mapping):
        summary = {**synthesized, **dict(existing)}
        expected_keys = set(synthesized)
        source = (
            "recorded"
            if expected_keys <= set(existing)
            else "recorded_partial_with_synthesized_defaults"
        )
        summary.setdefault("source", source)
        return summary
    synthesized["source"] = "synthesized_from_legacy_cycle"
    return synthesized


def normalized_failure_head_lines(value: Any, *, limit: int) -> list[str]:
    """Return compact non-boilerplate failure-head lines."""

    lines: list[str] = []
    for line in command_output_text(value).splitlines():
        text = line.strip()
        if not text or is_pytest_session_noise(text):
            continue
        lines.append(text)
        if len(lines) >= limit:
            break
    return lines


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


def classify_artifact_failure_kind(
    artifact: Mapping[str, Any],
    *,
    quality_detector: Callable[[str], bool] | None = None,
    quality_failure_kind: str = "quality",
    provider_http_markers: set[str] | frozenset[str] = DEFAULT_PROVIDER_HTTP_FAILURE_MARKERS,
    timeout_markers: set[str] | frozenset[str] = DEFAULT_TIMEOUT_FAILURE_MARKERS,
    parse_markers: set[str] | frozenset[str] = DEFAULT_PARSE_FAILURE_MARKERS,
    validation_markers: set[str] | frozenset[str] = DEFAULT_VALIDATION_FAILURE_MARKERS,
    validation_detector: Callable[[str], bool] | None = None,
    default_failure_kind: str = "invalid_no_change",
) -> str:
    """Classify a daemon artifact by explicit kind, validation text, and common provider failures."""

    text = artifact_validation_text(artifact)
    lower = text.lower()
    if quality_detector is not None and quality_detector(text):
        return quality_failure_kind
    explicit = str(artifact.get("failure_kind") or "")
    if explicit:
        return explicit
    if any(marker in lower for marker in provider_http_markers):
        return "provider_http_403"
    if any(marker in lower for marker in timeout_markers):
        return "timeout"
    if any(marker in lower for marker in parse_markers):
        return "parse"
    if validation_detector is not None and validation_detector(text):
        return "validation"
    if any(marker in lower for marker in validation_markers) or ("ts" in lower and "error" in lower):
        return "validation"
    return default_failure_kind


def render_proposal_feedback(
    *,
    summary: str = "",
    failure_kind: str = "",
    errors: Sequence[Any] = (),
    diagnostic_context: str = "",
    raw_response: str = "",
    diagnostic_label: str = "diagnostic_context",
    max_errors: int = 3,
    raw_response_limit: int = 1200,
) -> str:
    """Render compact retry feedback for a rejected daemon proposal."""

    selected_errors = [str(error) for error in list(errors)[: max(0, int(max_errors))]]
    return "\n".join(
        [
            f"summary={summary or '<empty>'}",
            f"failure_kind={failure_kind or '<empty>'}",
            f"errors={'; '.join(selected_errors) if selected_errors else '<none>'}",
            f"{diagnostic_label}={diagnostic_context or '<none>'}",
            f"response_prefix={str(raw_response or '')[: max(0, int(raw_response_limit))]}",
        ]
    )


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


def render_file_edit_diagnostic_context(
    *,
    errors: Sequence[Any] | str,
    files: Sequence[Mapping[str, Any]],
    radius: int = 2,
    limit: int = 6000,
    diagnostic_renderer: Callable[..., str] = render_typescript_diagnostic_context,
) -> str:
    """Render diagnostic context for complete-file edits and error text."""

    if not files or not errors:
        return ""
    edits_by_path = file_edits_by_path(files)
    if not edits_by_path:
        return ""
    text = errors if isinstance(errors, str) else "\n".join(str(error) for error in errors)
    return diagnostic_renderer(text, edits_by_path, radius=radius, limit=limit)


DEFAULT_FILE_REPLACEMENT_RETRY_CORRECTIONS = (
    "- Return ONLY one JSON object. No markdown fence, no explanation before or after it.",
    "- Use the `files` array with complete replacement file contents.",
    "- Leave `patch` as an empty string.",
    "- Do not describe a plan, mention inability to edit files, or return status text. The entire response must parse as JSON.",
    "- If the previous response was prose, convert that intent into complete file replacements now.",
)


def build_file_replacement_retry_prompt(
    original_prompt: str,
    previous_feedback: str,
    *,
    attempt: int,
    attempts: int,
    correction_lines: Sequence[str] = DEFAULT_FILE_REPLACEMENT_RETRY_CORRECTIONS,
) -> str:
    """Build a retry prompt for JSON complete-file replacement proposal flows."""

    lines = [str(line) for line in correction_lines if str(line)]
    return f"""{original_prompt}

Previous proposal attempt {attempt - 1} of {attempts} was rejected before any files could be used by the daemon.

Rejection details:
{previous_feedback}

Critical correction for attempt {attempt}:
{chr(10).join(lines)}
"""


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
