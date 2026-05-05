"""Reusable file-replacement apply flow for todo daemons."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .engine import CommandResult, Proposal
from .runner import TodoDaemonHooks, TodoDaemonRunner

ApplyProposalHook = Callable[[Proposal, Any], Proposal]


@dataclass(frozen=True)
class FileReplacementHooks:
    """Domain hooks for validating and persisting file-replacement proposals."""

    validate_write_path: Callable[[str], list[str]]
    temporary_validation_worktree: Callable[[Any], AbstractContextManager[Path]]
    materialize_proposal_in_worktree: Callable[[Proposal, Any, Path], list[str]]
    proposal_diff_from_worktree: Callable[[Any, Path, Iterable[str]], str]
    validation_commands_for_proposal: Callable[[Proposal, Any], tuple[tuple[str, ...], ...]]
    run_validation: Callable[[Any, tuple[tuple[str, ...], ...]], list[CommandResult]]
    worktree_config: Callable[[Any, Path], Any]
    syntax_preflight: Callable[[Path, list[str], Any], tuple[list[CommandResult], list[str], str]]
    has_visible_source_change: Callable[[Iterable[str]], bool]
    attempt_validation_repair: Callable[[Proposal, Any, Path], tuple[bool, list[str], str]]
    proposal_files_from_worktree: Callable[[Path, Iterable[str]], list[dict[str, str]]]
    promote_worktree_files: Callable[[Any, Path, Iterable[str]], None]
    verify_promoted_worktree_files: Callable[[Any, Path, Iterable[str]], list[str]]
    persist_failed_work: Callable[[Proposal, Any, str, str, str], None]
    persist_accepted_work: Callable[[Proposal, Any, str, str], None]
    no_visible_source_change_message: str = (
        "Accepted work must promote at least one visible source or fixture file; "
        "runtime-only progress records are not sufficient."
    )


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
        changed = hooks.materialize_proposal_in_worktree(proposal, config, worktree)
        proposal.changed_files = changed
        if not changed:
            proposal.errors.append("Proposal made no content changes.")
            proposal.failure_kind = "no_change"
            proposal.validation_results = hooks.run_validation(
                hooks.worktree_config(config, worktree),
                proposal_validation_commands,
            )
            hooks.persist_failed_work(proposal, config, "", "no_change", "ephemeral_worktree")
            return proposal

        if proposal.requires_visible_source_change and not hooks.has_visible_source_change(changed):
            proposal.errors.append(hooks.no_visible_source_change_message)
            proposal.failure_kind = "no_visible_source_change"
            proposal.validation_results = hooks.run_validation(
                hooks.worktree_config(config, worktree),
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
            hooks.worktree_config(config, worktree),
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
