"""Reusable file-replacement apply flow for todo daemons."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .artifacts import (
    DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
    persist_proposal_accepted_work,
    persist_proposal_failed_work,
)
from .engine import (
    CommandResult,
    Proposal,
    compact_message,
    config_repo_root,
    dataclass_worktree_config,
    extract_json,
    looks_like_empty_codex_event_stream,
    materialize_proposal_files,
    normalize_file_edits,
    normalize_task_references,
    normalize_validation_commands,
    promote_worktree_files,
    proposal_diff_from_worktree,
    proposal_files_from_worktree as engine_proposal_files_from_worktree,
    temporary_validation_worktree,
    verify_promoted_worktree_files,
)
from .runner import TodoDaemonHooks, TodoDaemonRunner

ApplyProposalHook = Callable[[Proposal, Any], Proposal]
DIFF_BLOCK_RE = re.compile(r"```(?:diff|patch)\s*([\s\S]*?)\s*```", re.IGNORECASE)
DEFAULT_FILE_REPLACEMENT_ACCEPTED_DIR = Path(".daemon/accepted-work")
DEFAULT_FILE_REPLACEMENT_FAILED_DIR = Path(".daemon/failed-work")


@dataclass(frozen=True)
class FileReplacementResponse:
    """Parsed JSON/file-replacement or fenced-diff proposal response."""

    summary: str = ""
    impact: str = ""
    patch: str = ""
    files: list[dict[str, str]] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    validation_commands: list[list[str]] = field(default_factory=list)
    raw_response: str = ""
    errors: list[str] = field(default_factory=list)
    failure_kind: str = ""


def parse_file_replacement_response(
    text: str,
    *,
    parse_error_message: str = "LLM response did not contain JSON or a fenced diff patch.",
    empty_codex_event_stream_message: str = "Codex returned JSONL startup events without an assistant proposal.",
    empty_codex_event_stream_failure_kind: str = "codex_empty_event_stream",
    fenced_diff_summary: str = "Patch extracted from fenced diff block.",
) -> FileReplacementResponse:
    """Parse a model response into reusable file replacements or a patch fallback."""

    parsed = extract_json(text)
    if parsed is not None:
        return FileReplacementResponse(
            summary=str(parsed.get("summary", "")),
            impact=str(parsed.get("impact", "")),
            patch=str(parsed.get("patch", "")),
            files=normalize_file_edits(parsed.get("files", [])),
            tasks=normalize_task_references(parsed.get("tasks", [])),
            validation_commands=normalize_validation_commands(parsed.get("validation_commands", [])),
            raw_response=text,
        )

    diff_match = DIFF_BLOCK_RE.search(text)
    if diff_match:
        return FileReplacementResponse(summary=fenced_diff_summary, patch=diff_match.group(1), raw_response=text)

    if looks_like_empty_codex_event_stream(text):
        return FileReplacementResponse(
            raw_response=text,
            errors=[empty_codex_event_stream_message],
            failure_kind=empty_codex_event_stream_failure_kind,
        )

    return FileReplacementResponse(raw_response=text, errors=[parse_error_message])


def build_file_replacement_validation_repair_prompt(
    proposal: Proposal,
    *,
    subject: str = "todo daemon candidate",
    repair_rules: Iterable[str] = (),
    response_shape: str = (
        '{"summary":"short repair summary","impact":"why this fixes validation",'
        '"files":[{"path":"...","content":"complete replacement"}]}'
    ),
    command_output_limit: int = 1200,
    no_failing_results_message: str = "No failing command output was captured.",
) -> str:
    """Render a reusable validation-repair prompt for complete-file proposals."""

    failed_results = "\n".join(
        json.dumps(result.compact(limit=command_output_limit), sort_keys=True)
        for result in proposal.validation_results
        if not result.ok
    )
    files = "\n".join(f"- {path}" for path in proposal.changed_files) or "- none"
    rules = tuple(str(rule).strip() for rule in repair_rules if str(rule).strip())
    rules_text = "\n".join(f"- {rule}" for rule in rules) or "- Keep the repair focused on the failed validation."
    return f"""
You are repairing a {subject} inside an isolated temporary validation worktree.

Return exactly one JSON object with complete file replacements. Do not include markdown.

Original task:
{proposal.target_task}

Current failed candidate:
- summary: {proposal.summary}
- changed files:
{files}

Failing validation results:
{failed_results or no_failing_results_message}

Repair rules:
{rules_text}
- Return JSON in this shape:
{response_shape}
"""


def validation_worktree_for_spec(
    spec: Any,
) -> Callable[[Any], AbstractContextManager[Path]]:
    """Return a hook that opens a static validation-worktree spec."""

    return lambda _config: temporary_validation_worktree(spec)


def materialize_proposal_files_in_worktree(
    proposal: Proposal,
    _config: Any,
    worktree: Path,
) -> list[str]:
    """Materialize proposal complete-file replacements into a validation worktree."""

    return materialize_proposal_files(proposal, worktree)


def proposal_files_from_validation_worktree(worktree: Path, changed: Iterable[str]) -> list[dict[str, str]]:
    """Read complete-file proposal payloads back from a validation worktree."""

    return engine_proposal_files_from_worktree(worktree, changed)


def config_proposal_diff_from_worktree(
    config: Any,
    worktree: Path,
    changed: Iterable[str],
    *,
    repo_root_field: str = "repo_root",
) -> str:
    """Return a proposal diff using the daemon config's repository root."""

    return proposal_diff_from_worktree(config_repo_root(config, repo_root_field=repo_root_field), worktree, changed)


def config_promote_worktree_files(
    config: Any,
    worktree: Path,
    changed: Iterable[str],
    *,
    repo_root_field: str = "repo_root",
) -> None:
    """Promote accepted worktree files into the daemon config's repository root."""

    promote_worktree_files(config_repo_root(config, repo_root_field=repo_root_field), worktree, changed)


def config_verify_promoted_worktree_files(
    config: Any,
    worktree: Path,
    changed: Iterable[str],
    *,
    repo_root_field: str = "repo_root",
) -> list[str]:
    """Verify promoted files against the daemon config's repository root."""

    return verify_promoted_worktree_files(config_repo_root(config, repo_root_field=repo_root_field), worktree, changed)


def config_artifact_directory(
    config: Any,
    *,
    directory_field: str,
    default: Path,
) -> Path:
    """Return an artifact directory from config, falling back to a reusable default."""

    value = getattr(config, directory_field, default)
    return Path(value if value is not None else default)


def config_persist_failed_file_replacement_work(
    proposal: Proposal,
    config: Any,
    diff_text: str,
    reason: str,
    transport: str,
    *,
    failed_dir_field: str = "failed_work_dir",
    default_failed_dir: Path = DEFAULT_FILE_REPLACEMENT_FAILED_DIR,
    repo_root_field: str = "repo_root",
) -> None:
    """Persist failed complete-file proposal sidecars using config paths."""

    persist_proposal_failed_work(
        failed_dir=config_artifact_directory(
            config,
            directory_field=failed_dir_field,
            default=default_failed_dir,
        ),
        proposal=proposal,
        diff_text=diff_text,
        reason=reason,
        transport=transport,
        repo_root=config_repo_root(config, repo_root_field=repo_root_field),
    )


def config_persist_accepted_file_replacement_work(
    proposal: Proposal,
    config: Any,
    diff_text: str,
    transport: str,
    *,
    accepted_dir_field: str = "accepted_work_dir",
    default_accepted_dir: Path = DEFAULT_FILE_REPLACEMENT_ACCEPTED_DIR,
    sidecars_enabled_field: str = "accepted_work_sidecars",
    ledger_filename_field: str = "accepted_work_ledger_filename",
    repo_root_field: str = "repo_root",
) -> None:
    """Persist accepted complete-file proposal evidence and ledger rows using config paths."""

    ledger_filename = str(
        getattr(config, ledger_filename_field, DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME)
        or DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME
    )
    persist_proposal_accepted_work(
        repo_root=config_repo_root(config, repo_root_field=repo_root_field),
        accepted_dir=config_artifact_directory(
            config,
            directory_field=accepted_dir_field,
            default=default_accepted_dir,
        ),
        proposal=proposal,
        diff_text=diff_text,
        transport=transport,
        write_sidecars_enabled=bool(getattr(config, sidecars_enabled_field, False)),
        ledger_filename=ledger_filename,
    )


def no_file_replacement_validation_repair(
    proposal: Proposal,
    _config: Any,
    _worktree: Path,
) -> tuple[bool, list[str], str]:
    """Return the standard no-op validation repair result for file-replacement hooks."""

    return False, proposal.changed_files, ""


def attempt_file_replacement_validation_repair(
    proposal: Proposal,
    config: Any,
    worktree: Path,
    *,
    enabled: bool,
    max_attempts: int,
    build_prompt: Callable[[Proposal, Any], str],
    call_repair_model: Callable[[str, Any], str],
    parse_repair: Callable[[str], Proposal],
    validate_write_path: Callable[[str], list[str]],
    syntax_preflight: Callable[[Path, list[str], Any], tuple[list[CommandResult], list[str], str]],
    run_validation: Callable[[Any, tuple[tuple[str, ...], ...]], list[CommandResult]],
    validation_commands_for_proposal: Callable[[Proposal, Any], tuple[tuple[str, ...], ...]],
    materialize_proposal_in_worktree: Callable[[Proposal, Any, Path], list[str]] = materialize_proposal_files_in_worktree,
    proposal_diff_from_worktree: Callable[[Any, Path, Iterable[str]], str] = config_proposal_diff_from_worktree,
    proposal_files_from_worktree: Callable[[Path, Iterable[str]], list[dict[str, str]]] = proposal_files_from_validation_worktree,
    worktree_config: Callable[[Any, Path], Any] = dataclass_worktree_config,
) -> tuple[bool, list[str], str]:
    """Attempt one validation-repair pass for a complete-file replacement proposal."""

    if not enabled or max_attempts <= 0:
        return False, proposal.changed_files, ""
    try:
        raw = call_repair_model(build_prompt(proposal, config), config)
        repair = parse_repair(raw)
    except BaseException as exc:
        proposal.errors.append(f"Validation repair pass failed before producing JSON: {compact_message(exc)}")
        return False, proposal.changed_files, ""
    repair.target_task = proposal.target_task
    repair_errors: list[str] = []
    for item in repair.files:
        repair_errors.extend(validate_write_path(item["path"]))
    if repair_errors:
        proposal.errors.extend(f"Validation repair pass rejected write path: {error}" for error in repair_errors)
        return False, proposal.changed_files, ""
    if not repair.files:
        proposal.errors.append("Validation repair pass produced no file replacements.")
        return False, proposal.changed_files, ""

    changed = list(dict.fromkeys(proposal.changed_files + materialize_proposal_in_worktree(repair, config, worktree)))
    repair_results, repair_preflight_errors, repair_failure_kind = syntax_preflight(worktree, changed, config)
    proposal.validation_results = repair_results
    if repair_preflight_errors:
        proposal.errors.extend("Validation repair pass syntax preflight failed: " + error for error in repair_preflight_errors)
        proposal.failure_kind = repair_failure_kind or "syntax_preflight"
        return False, changed, proposal_diff_from_worktree(config, worktree, changed)

    proposal.validation_results = run_validation(
        worktree_config(config, worktree),
        validation_commands_for_proposal(proposal, config),
    )
    if not all(result.ok for result in proposal.validation_results):
        proposal.errors.append("Validation repair pass failed; candidate worktree was not promoted.")
        proposal.failure_kind = "validation"
        return False, changed, proposal_diff_from_worktree(config, worktree, changed)

    proposal.summary = repair.summary or proposal.summary
    proposal.impact = repair.impact or proposal.impact
    proposal.files = proposal_files_from_worktree(worktree, changed)
    proposal.changed_files = changed
    proposal.errors = []
    return True, changed, proposal_diff_from_worktree(config, worktree, changed)


@dataclass(frozen=True)
class FileReplacementHooks:
    """Domain hooks for validating and persisting file-replacement proposals."""

    validate_write_path: Callable[[str], list[str]]
    temporary_validation_worktree: Callable[[Any], AbstractContextManager[Path]]
    validation_commands_for_proposal: Callable[[Proposal, Any], tuple[tuple[str, ...], ...]]
    run_validation: Callable[[Any, tuple[tuple[str, ...], ...]], list[CommandResult]]
    syntax_preflight: Callable[[Path, list[str], Any], tuple[list[CommandResult], list[str], str]]
    has_visible_source_change: Callable[[Iterable[str]], bool]
    attempt_validation_repair: Callable[
        [Proposal, Any, Path],
        tuple[bool, list[str], str],
    ] = no_file_replacement_validation_repair
    persist_failed_work: Callable[[Proposal, Any, str, str, str], None] = config_persist_failed_file_replacement_work
    persist_accepted_work: Callable[[Proposal, Any, str, str], None] = config_persist_accepted_file_replacement_work
    materialize_proposal_in_worktree: Callable[[Proposal, Any, Path], list[str]] = materialize_proposal_files_in_worktree
    proposal_diff_from_worktree: Callable[[Any, Path, Iterable[str]], str] = config_proposal_diff_from_worktree
    proposal_files_from_worktree: Callable[[Path, Iterable[str]], list[dict[str, str]]] = proposal_files_from_validation_worktree
    promote_worktree_files: Callable[[Any, Path, Iterable[str]], None] = config_promote_worktree_files
    verify_promoted_worktree_files: Callable[[Any, Path, Iterable[str]], list[str]] = config_verify_promoted_worktree_files
    worktree_config: Callable[[Any, Path], Any] = dataclass_worktree_config
    no_visible_source_change_message: str = (
        "Accepted work must promote at least one visible source or fixture file; "
        "runtime-only progress records are not sufficient."
    )


def build_config_file_replacement_hooks(
    *,
    validate_write_path: Callable[[str], list[str]],
    temporary_validation_worktree: Callable[[Any], AbstractContextManager[Path]],
    validation_commands_for_proposal: Callable[[Proposal, Any], tuple[tuple[str, ...], ...]],
    run_validation: Callable[[Any, tuple[tuple[str, ...], ...]], list[CommandResult]],
    syntax_preflight: Callable[[Path, list[str], Any], tuple[list[CommandResult], list[str], str]],
    has_visible_source_change: Callable[[Iterable[str]], bool],
    attempt_validation_repair: Callable[
        [Proposal, Any, Path],
        tuple[bool, list[str], str],
    ] = no_file_replacement_validation_repair,
    accepted_dir_field: str = "accepted_work_dir",
    failed_dir_field: str = "failed_work_dir",
    sidecars_enabled_field: str = "accepted_work_sidecars",
    ledger_filename_field: str = "accepted_work_ledger_filename",
    default_accepted_dir: Path = DEFAULT_FILE_REPLACEMENT_ACCEPTED_DIR,
    default_failed_dir: Path = DEFAULT_FILE_REPLACEMENT_FAILED_DIR,
    no_visible_source_change_message: str = (
        "Accepted work must promote at least one visible source or fixture file; "
        "runtime-only progress records are not sufficient."
    ),
    materialize_proposal_in_worktree: Callable[[Proposal, Any, Path], list[str]] = materialize_proposal_files_in_worktree,
    proposal_diff_from_worktree: Callable[[Any, Path, Iterable[str]], str] = config_proposal_diff_from_worktree,
    proposal_files_from_worktree: Callable[[Path, Iterable[str]], list[dict[str, str]]] = proposal_files_from_validation_worktree,
    promote_worktree_files: Callable[[Any, Path, Iterable[str]], None] = config_promote_worktree_files,
    verify_promoted_worktree_files: Callable[[Any, Path, Iterable[str]], list[str]] = config_verify_promoted_worktree_files,
    worktree_config: Callable[[Any, Path], Any] = dataclass_worktree_config,
) -> FileReplacementHooks:
    """Build file-replacement hooks with reusable config-backed artifact persistence."""

    def persist_failed_work(
        proposal: Proposal,
        config: Any,
        diff_text: str,
        reason: str,
        transport: str,
    ) -> None:
        config_persist_failed_file_replacement_work(
            proposal,
            config,
            diff_text,
            reason,
            transport,
            failed_dir_field=failed_dir_field,
            default_failed_dir=default_failed_dir,
        )

    def persist_accepted_work(
        proposal: Proposal,
        config: Any,
        diff_text: str,
        transport: str,
    ) -> None:
        config_persist_accepted_file_replacement_work(
            proposal,
            config,
            diff_text,
            transport,
            accepted_dir_field=accepted_dir_field,
            default_accepted_dir=default_accepted_dir,
            sidecars_enabled_field=sidecars_enabled_field,
            ledger_filename_field=ledger_filename_field,
        )

    return FileReplacementHooks(
        validate_write_path=validate_write_path,
        temporary_validation_worktree=temporary_validation_worktree,
        validation_commands_for_proposal=validation_commands_for_proposal,
        run_validation=run_validation,
        syntax_preflight=syntax_preflight,
        has_visible_source_change=has_visible_source_change,
        attempt_validation_repair=attempt_validation_repair,
        persist_failed_work=persist_failed_work,
        persist_accepted_work=persist_accepted_work,
        materialize_proposal_in_worktree=materialize_proposal_in_worktree,
        proposal_diff_from_worktree=proposal_diff_from_worktree,
        proposal_files_from_worktree=proposal_files_from_worktree,
        promote_worktree_files=promote_worktree_files,
        verify_promoted_worktree_files=verify_promoted_worktree_files,
        worktree_config=worktree_config,
        no_visible_source_change_message=no_visible_source_change_message,
    )


@dataclass(frozen=True)
class ProposalPreflightPolicy:
    """Configurable preflight guardrails for proposal patch/file payloads."""

    forbidden_snippets: tuple[str, ...] = ()
    forbidden_snippet_message: str = "Rejected proposal because it contains forbidden snippet {snippet}."
    prefer_file_edits: bool = False
    file_edit_required_prefixes: tuple[str, ...] = ()
    file_edit_excluded_prefixes: tuple[str, ...] = ()
    file_edit_patch_exempt_transports: frozenset[str] = frozenset({"worktree"})
    file_edit_required_message: str = (
        "Rejected proposal because matching path changes must use JSON `files` complete replacements."
    )
    implementation_required_prefixes: tuple[str, ...] = ()
    implementation_excluded_prefixes: tuple[str, ...] = ()
    non_implementation_task_keywords: tuple[str, ...] = ()
    implementation_required_message: str = (
        "Rejected proposal because the selected task appears to require implementation work, "
        "but the proposal does not change a required implementation file."
    )
    fixture_task_keywords: tuple[str, ...] = ()
    fixture_test_prefixes: tuple[str, ...] = ()
    fixture_test_suffixes: tuple[str, ...] = ()
    fixture_test_required_message: str = (
        "Rejected proposal because fixture work must update a corresponding validation test file."
    )


def task_title_contains_any(task_or_title: Any, keywords: Iterable[str]) -> bool:
    """Return whether a task-like object or title contains any keyword."""

    if task_or_title is None:
        return False
    title = task_or_title if isinstance(task_or_title, str) else getattr(task_or_title, "title", "")
    lowered = str(title or "").lower()
    return any(str(keyword).lower() in lowered for keyword in keywords)


def paths_include_required_change(
    paths: Iterable[str],
    *,
    prefixes: Iterable[str],
    excluded_prefixes: Iterable[str] = (),
    suffixes: Iterable[str] = (),
) -> bool:
    """Return whether changed paths contain an included, non-excluded path."""

    include = tuple(str(prefix) for prefix in prefixes if str(prefix))
    exclude = tuple(str(prefix) for prefix in excluded_prefixes if str(prefix))
    required_suffixes = tuple(str(suffix) for suffix in suffixes if str(suffix))
    for path in paths:
        text = str(path)
        if include and not text.startswith(include):
            continue
        if exclude and text.startswith(exclude):
            continue
        if required_suffixes and not text.endswith(required_suffixes):
            continue
        return True
    return False


def preflight_proposal_payload(
    *,
    patch: str,
    files: Iterable[dict[str, Any]],
    paths: Iterable[str],
    selected_task: Any = None,
    proposal_transport: str = "",
    default_transport: str = "",
    policy: ProposalPreflightPolicy,
) -> list[str]:
    """Run reusable preflight checks for patch/file proposal payloads."""

    file_list = list(files)
    path_list = [str(path) for path in paths]
    errors: list[str] = []
    candidates = [patch, *(str(edit.get("content", "")) for edit in file_list)]
    for snippet in policy.forbidden_snippets:
        if any(snippet in candidate for candidate in candidates):
            errors.append(policy.forbidden_snippet_message.format(snippet=snippet))
    has_file_required_change = paths_include_required_change(
        path_list,
        prefixes=policy.file_edit_required_prefixes,
        excluded_prefixes=policy.file_edit_excluded_prefixes,
    )
    patch_exempt = (
        proposal_transport in policy.file_edit_patch_exempt_transports
        or default_transport in policy.file_edit_patch_exempt_transports
    )
    if policy.prefer_file_edits and patch.strip() and not file_list and has_file_required_change and not patch_exempt:
        errors.append(policy.file_edit_required_message)

    if selected_task is not None and path_list:
        implementation_change = paths_include_required_change(
            path_list,
            prefixes=policy.implementation_required_prefixes,
            excluded_prefixes=policy.implementation_excluded_prefixes,
        )
        allows_non_implementation = task_title_contains_any(
            selected_task,
            policy.non_implementation_task_keywords,
        )
        if policy.implementation_required_prefixes and not allows_non_implementation and not implementation_change:
            errors.append(policy.implementation_required_message)

        fixture_task = task_title_contains_any(selected_task, policy.fixture_task_keywords)
        fixture_test_change = paths_include_required_change(
            path_list,
            prefixes=policy.fixture_test_prefixes,
            suffixes=policy.fixture_test_suffixes,
        )
        if policy.fixture_task_keywords and fixture_task and not fixture_test_change:
            errors.append(policy.fixture_test_required_message)
    return errors


def apply_file_replacement_proposal(
    proposal: Proposal,
    config: Any,
    hooks: FileReplacementHooks,
) -> Proposal:
    """Validate and promote a complete-file replacement proposal.

    The flow intentionally avoids patch files: candidate files are materialized
    in a temporary validation worktree, checked there, then promoted only after
    all validation gates pass.
    """

    proposal_validation_commands = hooks.validation_commands_for_proposal(proposal, config)
    preflight_errors: list[str] = []
    for item in proposal.files:
        preflight_errors.extend(hooks.validate_write_path(item["path"]))
    if preflight_errors:
        proposal.errors.extend(preflight_errors)
        proposal.failure_kind = "preflight"
        hooks.persist_failed_work(proposal, config, "", "preflight", "direct")
        return proposal

    with hooks.temporary_validation_worktree(config) as worktree:
        worktree_config = hooks.worktree_config(config, worktree)
        changed = hooks.materialize_proposal_in_worktree(proposal, config, worktree)
        proposal.changed_files = changed
        if not changed:
            proposal.errors.append("Proposal made no content changes.")
            proposal.failure_kind = "no_change"
            proposal.validation_results = hooks.run_validation(
                worktree_config,
                proposal_validation_commands,
            )
            hooks.persist_failed_work(proposal, config, "", "no_change", "ephemeral_worktree")
            return proposal

        if proposal.requires_visible_source_change and not hooks.has_visible_source_change(changed):
            proposal.errors.append(hooks.no_visible_source_change_message)
            proposal.failure_kind = "no_visible_source_change"
            proposal.validation_results = hooks.run_validation(
                worktree_config,
                proposal_validation_commands,
            )
            hooks.persist_failed_work(
                proposal,
                config,
                hooks.proposal_diff_from_worktree(config, worktree, changed),
                "no_visible_source_change",
                "ephemeral_worktree",
            )
            return proposal

        diff_text = hooks.proposal_diff_from_worktree(config, worktree, changed)
        proposal.validation_results, preflight_errors, failure_kind = hooks.syntax_preflight(
            worktree,
            changed,
            config,
        )
        if preflight_errors:
            proposal.errors.extend(preflight_errors)
            proposal.failure_kind = failure_kind
            hooks.persist_failed_work(
                proposal,
                config,
                diff_text,
                "syntax_preflight",
                "ephemeral_worktree",
            )
            return proposal

        proposal.validation_results = hooks.run_validation(
            worktree_config,
            proposal_validation_commands,
        )
        if not all(result.ok for result in proposal.validation_results):
            repaired, changed, repair_diff = hooks.attempt_validation_repair(proposal, config, worktree)
            diff_text = repair_diff or hooks.proposal_diff_from_worktree(config, worktree, changed)
            proposal.changed_files = changed
            if not repaired:
                if not proposal.failure_kind:
                    proposal.errors.append("Validation failed in temporary worktree; candidate was not promoted.")
                    proposal.failure_kind = "validation"
                hooks.persist_failed_work(
                    proposal,
                    config,
                    diff_text,
                    proposal.failure_kind or "validation",
                    "ephemeral_worktree",
                )
                return proposal

        hooks.promote_worktree_files(config, worktree, proposal.changed_files)
        promotion_errors = hooks.verify_promoted_worktree_files(config, worktree, proposal.changed_files)
        proposal.promotion_errors = promotion_errors
        proposal.promotion_verified = not promotion_errors
        if promotion_errors:
            proposal.errors.extend(promotion_errors)
            proposal.failure_kind = "promotion"
            hooks.persist_failed_work(proposal, config, diff_text, "promotion", "ephemeral_worktree")
            return proposal
        proposal.applied = True
        hooks.persist_accepted_work(proposal, config, diff_text, "ephemeral_worktree")
    return proposal


def build_file_replacement_apply_proposal(
    file_replacement_hooks: FileReplacementHooks,
) -> ApplyProposalHook:
    """Return a runner-compatible apply hook for file-replacement proposals."""

    return lambda proposal, config: apply_file_replacement_proposal(
        proposal,
        config,
        file_replacement_hooks,
    )


def bind_file_replacement_apply_hook(
    runner_hooks: TodoDaemonHooks,
    file_replacement_hooks: FileReplacementHooks,
) -> TodoDaemonHooks:
    """Return runner hooks whose apply step uses the reusable file-replacement flow."""

    return TodoDaemonHooks(
        parse_tasks=runner_hooks.parse_tasks,
        select_task=runner_hooks.select_task,
        replace_task_mark=runner_hooks.replace_task_mark,
        update_generated_status=runner_hooks.update_generated_status,
        produce_proposal=runner_hooks.produce_proposal,
        apply_proposal=build_file_replacement_apply_proposal(file_replacement_hooks),
        run_validation=runner_hooks.run_validation,
        should_skip_validation=runner_hooks.should_skip_validation,
        is_retryable_failure=runner_hooks.is_retryable_failure,
        failure_block_threshold=runner_hooks.failure_block_threshold,
        failure_count_for_block=runner_hooks.failure_count_for_block,
        should_sleep_between_cycles=runner_hooks.should_sleep_between_cycles,
        exception_diagnostic=runner_hooks.exception_diagnostic,
        pre_task_block=runner_hooks.pre_task_block,
        no_eligible_summary=runner_hooks.no_eligible_summary,
        exception_summary=runner_hooks.exception_summary,
        exception_impact=runner_hooks.exception_impact,
    )


class FileReplacementTodoDaemonRunner(TodoDaemonRunner):
    """Concrete reusable daemon for JSON file-replacement todo workflows."""

    def __init__(
        self,
        config: Any,
        runner_hooks: TodoDaemonHooks,
        file_replacement_hooks: FileReplacementHooks,
    ) -> None:
        super().__init__(
            config,
            bind_file_replacement_apply_hook(runner_hooks, file_replacement_hooks),
        )
