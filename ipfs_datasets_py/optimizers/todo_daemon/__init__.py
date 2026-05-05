"""Reusable lifecycle helpers for unattended optimizer todo daemons."""

from .core import (
    DaemonHealth,
    EnsureResult,
    ManagedDaemonSpec,
    StopResult,
    check_daemon_health,
    ensure_daemon_running,
    stop_daemon,
)
from .engine import (
    CommandResult,
    PathPolicy,
    Proposal,
    Task,
    ValidationWorkspaceSpec,
    append_jsonl,
    atomic_write_json,
    cleanup_stale_validation_worktrees,
    compact_message,
    copy_if_exists,
    diff_for_file,
    extract_json,
    link_or_copy_if_exists,
    materialize_proposal_files,
    normalized_relative_path,
    parse_json_proposal,
    parse_markdown_tasks,
    proposal_diff_from_worktree,
    proposal_files_from_worktree,
    promote_worktree_files,
    read_text,
    run_command,
    select_task,
    temporary_validation_worktree,
    utc_now,
    verify_promoted_worktree_files,
    workspace_artifact_payload,
    worktree_marker_payload,
)
from .plans import PlanTask, extract_plan_tasks, replace_checkbox_mark, strip_daemon_task_board
from .runner import PreTaskBlock, TodoDaemonHooks, TodoDaemonRunner

__all__ = [
    "CommandResult",
    "DaemonHealth",
    "EnsureResult",
    "ManagedDaemonSpec",
    "PathPolicy",
    "PlanTask",
    "PreTaskBlock",
    "Proposal",
    "StopResult",
    "Task",
    "TodoDaemonHooks",
    "TodoDaemonRunner",
    "ValidationWorkspaceSpec",
    "append_jsonl",
    "atomic_write_json",
    "build_legal_parser_spec",
    "check_daemon_health",
    "check_legal_parser_health",
    "cleanup_stale_validation_worktrees",
    "compact_message",
    "copy_if_exists",
    "diff_for_file",
    "extract_json",
    "extract_plan_tasks",
    "ensure_daemon_running",
    "ensure_legal_parser_daemon",
    "legal_parser_launch_env",
    "link_or_copy_if_exists",
    "materialize_proposal_files",
    "normalized_relative_path",
    "parse_json_proposal",
    "parse_markdown_tasks",
    "proposal_diff_from_worktree",
    "proposal_files_from_worktree",
    "promote_worktree_files",
    "read_text",
    "replace_checkbox_mark",
    "run_command",
    "select_task",
    "stop_daemon",
    "stop_legal_parser_daemon",
    "strip_daemon_task_board",
    "temporary_validation_worktree",
    "utc_now",
    "verify_promoted_worktree_files",
    "workspace_artifact_payload",
    "worktree_marker_payload",
]


_LEGAL_PARSER_EXPORTS = {
    "build_legal_parser_spec",
    "check_legal_parser_health",
    "ensure_legal_parser_daemon",
    "legal_parser_launch_env",
    "stop_legal_parser_daemon",
}


def __getattr__(name):
    if name in _LEGAL_PARSER_EXPORTS:
        from . import legal_parser

        return getattr(legal_parser, name)
    raise AttributeError(name)
