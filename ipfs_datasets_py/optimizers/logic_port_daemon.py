"""Daemon for iteratively porting Python logic requirements to TypeScript.

The daemon is intentionally conservative:

- it uses :mod:`ipfs_datasets_py.optimizers.common` session tooling;
- it calls ``ipfs_datasets_py.llm_router.generate_text`` with ``gpt-5.5`` by
  default for legacy JSON/file proposals;
- by default it asks Codex to edit an isolated Git worktree directly and then
  harvests Git's canonical audit diff plus complete file replacements;
- it keeps legacy llm_router JSON/diff proposal mode available as an explicit
  fallback for debugging old proposal paths;
- it runs a configured validation command list after each candidate change;
- it never executes arbitrary shell commands returned by the model.

This is development tooling for the repository. It does not add a runtime
server dependency to the browser-native TypeScript logic port.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizationContext,
    OptimizerConfig,
)
from ipfs_datasets_py.optimizers.common.log_schema_v3 import (
    log_error,
    log_iteration_complete,
    log_iteration_started,
    log_session_complete,
    log_session_start,
)
from ipfs_datasets_py.optimizers.todo_daemon.engine import (
    CommandResult,
    atomic_write_json as _shared_atomic_write_json,
    compact_message as _shared_compact_message,
    extract_codex_event_text_candidates as _shared_extract_codex_event_text_candidates,
    extract_json as _shared_extract_json_object,
    extract_text_from_codex_event_object as _shared_extract_text_from_codex_event_object,
    looks_like_empty_codex_event_stream as _shared_looks_like_empty_codex_event_stream,
    normalize_file_edits as _shared_normalize_file_edits,
    normalize_task_references as _shared_normalize_task_references,
    normalize_validation_commands as _shared_normalize_validation_commands,
    read_text as _shared_read_text,
    run_command as _shared_run_command,
)
from ipfs_datasets_py.optimizers.todo_daemon.auto_commit import (
    AutoCommitConfig,
    auto_commit_paths as _shared_auto_commit_paths,
    build_auto_commit_subject as _shared_build_auto_commit_subject,
    repo_relative_pathspec as _shared_repo_relative_pathspec,
    safe_auto_commit_pathspecs as _shared_safe_auto_commit_pathspecs,
)
from ipfs_datasets_py.optimizers.todo_daemon.artifacts import (
    accepted_work_markdown_entry as _shared_accepted_work_markdown_entry,
    append_accepted_work_markdown_log as _shared_append_accepted_work_markdown_log,
    write_accepted_work_evidence_artifacts as _shared_write_accepted_work_evidence_artifacts,
)
from ipfs_datasets_py.optimizers.todo_daemon.context import (
    rank_relevant_context_file as _shared_rank_relevant_context_file,
    render_relevant_file_context as _shared_render_relevant_file_context,
    task_title_tokens as _shared_task_title_tokens,
)
from ipfs_datasets_py.optimizers.todo_daemon.diagnostics import (
    artifact_validation_text as _shared_artifact_validation_text,
    compact_status_artifact as _shared_compact_status_artifact,
    diagnostic_signatures as _shared_diagnostic_signatures,
    file_edits_by_path as _shared_file_edits_by_path,
    format_task_result_failure_context as _shared_format_task_result_failure_context,
    has_diagnostic_codes as _shared_has_diagnostic_codes,
    match_diagnostic_edit_path as _shared_match_diagnostic_edit_path,
    quality_failure_counts as _shared_quality_failure_counts,
    recent_rollback_failure_count as _shared_recent_rollback_failure_count,
    render_typescript_diagnostic_context as _shared_render_typescript_diagnostic_context,
    rollback_failure_counts as _shared_rollback_failure_counts,
)
from ipfs_datasets_py.optimizers.todo_daemon.llm import (
    LlmRouterInvocation,
    call_llm_router,
    call_with_thread_deadline as _shared_call_with_thread_deadline,
)
from ipfs_datasets_py.optimizers.todo_daemon.git_utils import (
    paths_from_patch_and_file_edits as _shared_paths_from_patch_and_file_edits,
    paths_from_unified_diff as _shared_paths_from_unified_diff,
)
from ipfs_datasets_py.optimizers.todo_daemon.file_replacement import (
    ProposalPreflightPolicy,
    paths_include_required_change as _shared_paths_include_required_change,
    preflight_proposal_payload as _shared_preflight_proposal_payload,
    task_title_contains_any as _shared_task_title_contains_any,
)
from ipfs_datasets_py.optimizers.todo_daemon.history import (
    current_task_failure_counts as _shared_current_task_failure_counts,
    last_task_attempt_index as _shared_last_task_attempt_index,
    normalize_task_label as _shared_normalize_task_label,
    read_daemon_results as _shared_read_daemon_results,
    recent_failure_count as _shared_recent_failure_count,
    recent_total_failure_count as _shared_recent_total_failure_count,
    rounds_since_last_valid as _shared_rounds_since_last_valid,
    same_task_label as _shared_same_task_label,
    task_failure_summary as _shared_task_failure_summary,
)
from ipfs_datasets_py.optimizers.todo_daemon.status import (
    build_heartbeat_status_payload as _shared_build_heartbeat_status_payload,
    status_started_at as _shared_status_started_at,
)
from ipfs_datasets_py.optimizers.todo_daemon.task_board import (
    focused_task_board_excerpt as _shared_focused_task_board_excerpt,
    truncate_text as _shared_truncate_text,
)
from ipfs_datasets_py.optimizers.todo_daemon.typescript import (
    obvious_typescript_text_damage as _shared_obvious_typescript_text_damage,
    repair_common_typescript_file_edits as _shared_repair_common_typescript_file_edits,
    repair_common_typescript_text_damage as _shared_repair_common_typescript_text_damage,
)
from ipfs_datasets_py.optimizers.todo_daemon.worktrees import (
    cleanup_stale_daemon_worktrees as _shared_cleanup_stale_daemon_worktrees,
    git_status_paths as _shared_git_status_paths,
    git_worktree_paths_from_porcelain as _shared_git_worktree_paths_from_porcelain,
    owner_pid_from_worktree as _shared_owner_pid_from_worktree,
    pid_command_line as _shared_pid_command_line,
    pid_is_alive as _shared_pid_is_alive,
    pid_looks_like_worktree_owner as _shared_pid_looks_like_worktree_owner,
    read_json_object as _shared_read_json_object,
    untracked_paths_from_git_status as _shared_untracked_paths_from_git_status,
    write_worktree_owner_file as _shared_write_worktree_owner_file,
)
from ipfs_datasets_py.optimizers.todo_daemon.plans import (
    PlanTask,
    blocked_task_backlog_markdown as _shared_blocked_task_backlog_markdown,
    build_blocked_task_backlog as _shared_build_blocked_task_backlog,
    clean_checkbox_title as _clean_checkbox_title,
    extract_plan_tasks,
    markdown_task_label as _shared_markdown_task_label,
    plan_task_from_latest_result as _shared_plan_task_from_latest_result,
    replace_checkbox_mark as _replace_checkbox_mark,
    select_blocked_plan_task as _shared_select_blocked_plan_task,
    select_next_plan_task as _shared_select_next_plan_task,
    status_from_checkbox as _status_from_checkbox,
    status_from_task_block as _status_from_task_block,
    strip_daemon_task_board as _strip_daemon_task_board,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_PLAN_DOCS = (
    "docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md",
)

DEFAULT_STATUS_DOCS = (
    "docs/LOGIC_PORT_PARITY.md",
)

DEFAULT_VALIDATION_COMMANDS = (
    ("npx", "tsc", "--noEmit"),
    ("npm", "run", "validate:logic-port"),
)

JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]*?)\s*```", re.IGNORECASE)
DIFF_BLOCK_RE = re.compile(r"```(?:diff|patch)\s*([\s\S]*?)\s*```", re.IGNORECASE)
FORBIDDEN_PATCH_SNIPPETS = (
    "from 'vitest'",
    'from "vitest"',
    "from '@jest/globals'",
    'from "@jest/globals"',
)

TYPESCRIPT_PREFLIGHT_ERROR_CODES = {
    "TS1003",
    "TS1005",
    "TS1011",
    "TS1068",
    "TS1109",
    "TS1128",
    "TS1138",
    "TS1144",
    "TS1434",
    "TS1442",
    "TS2314",
    "TS2322",
}
TYPESCRIPT_QUALITY_ERROR_CODES = TYPESCRIPT_PREFLIGHT_ERROR_CODES | {
    "TS2339",
    "TS2345",
    "TS2365",
    "TS7006",
}

ROLLBACK_QUALITY_FAILURE_KINDS = {
    "apply_check",
    "validation",
    "validation_repair",
    "file_repair_validation",
    "validation_repair_preflight",
    "preflight",
    "typescript_quality",
}


ALLOWED_WRITE_PREFIXES = (
    "src/lib/logic/",
    "docs/",
    "ipfs_datasets_py/docs/logic/",
)

NON_RUNTIME_TASK_KEYWORDS = (
    "fixture",
    "fixtures",
    "capture",
    "captures",
    "schema",
    "docs",
    "document",
    "documentation",
    "evaluate",
    "decide",
    "track",
    "record",
    "plan",
    "threshold",
    "acceptance",
)

FIXTURE_VALIDATION_TASK_KEYWORDS = (
    "fixture",
    "fixtures",
    "capture",
    "captures",
    "parity",
)

RUNTIME_LOGIC_PREFIX = "src/lib/logic/"
PARITY_FIXTURE_PREFIX = "src/lib/logic/parity/"
LOGIC_PORT_PREFLIGHT_POLICY = ProposalPreflightPolicy(
    forbidden_snippets=FORBIDDEN_PATCH_SNIPPETS,
    forbidden_snippet_message=(
        "Rejected proposal because it imports {snippet}; logic tests use Jest globals without test-framework imports."
    ),
    file_edit_required_prefixes=(RUNTIME_LOGIC_PREFIX,),
    file_edit_excluded_prefixes=(PARITY_FIXTURE_PREFIX,),
    file_edit_required_message=(
        "Rejected proposal because runtime TypeScript changes must use JSON `files` complete replacements "
        "instead of a unified diff patch for this daemon run."
    ),
    implementation_required_prefixes=(RUNTIME_LOGIC_PREFIX,),
    implementation_excluded_prefixes=(PARITY_FIXTURE_PREFIX,),
    non_implementation_task_keywords=NON_RUNTIME_TASK_KEYWORDS,
    implementation_required_message=(
        "Rejected proposal because the selected port-plan task appears to require implementation work, "
        "but the proposal does not change any runtime TypeScript file under src/lib/logic/."
    ),
    fixture_task_keywords=FIXTURE_VALIDATION_TASK_KEYWORDS,
    fixture_test_prefixes=(RUNTIME_LOGIC_PREFIX,),
    fixture_test_suffixes=(".test.ts",),
    fixture_test_required_message=(
        "Rejected proposal because fixture/capture/parity work must update a src/lib/logic/*.test.ts file "
        "that loads or asserts the generated fixture."
    ),
)


@dataclass
class LogicPortDaemonConfig:
    """Configuration for the logic-port daemon."""

    repo_root: Path = field(default_factory=lambda: Path.cwd())
    plan_docs: Tuple[Path, ...] = field(default_factory=lambda: tuple(Path(p) for p in DEFAULT_PLAN_DOCS))
    status_docs: Tuple[Path, ...] = field(default_factory=lambda: tuple(Path(p) for p in DEFAULT_STATUS_DOCS))
    typescript_logic_dir: Path = Path("src/lib/logic")
    python_logic_dir: Path = Path("ipfs_datasets_py/ipfs_datasets_py/logic")
    model_name: str = "gpt-5.5"
    provider: Optional[str] = None
    slice_mode: str = "balanced"
    max_iterations: int = 1
    interval_seconds: float = 0.0
    target_score: float = 0.99
    dry_run: bool = True
    validation_commands: Tuple[Tuple[str, ...], ...] = DEFAULT_VALIDATION_COMMANDS
    max_prompt_chars: int = 32000
    max_context_file_chars: int = 12000
    max_context_files: int = 6
    max_patch_lines: int = 180
    command_timeout_seconds: int = 300
    proposal_transport: str = "llm_router"
    worktree_edit_timeout_seconds: int = 300
    worktree_stale_after_seconds: int = 7200
    worktree_codex_sandbox: str = field(
        default_factory=lambda: os.environ.get(
            "LOGIC_PORT_DAEMON_WORKTREE_CODEX_SANDBOX",
            os.environ.get("IPFS_DATASETS_PY_CODEX_SANDBOX", "danger-full-access"),
        )
    )
    worktree_root: Path = field(default_factory=lambda: Path("ipfs_datasets_py/.daemon/logic-port-worktrees"))
    codex_bin: str = field(default_factory=lambda: os.environ.get("CODEX_BIN", "codex"))
    worktree_repair_attempts: int = 1
    max_new_tokens: int = 4096
    temperature: float = 0.1
    allow_local_fallback: bool = False
    llm_timeout_seconds: int = 300
    retry_interval_seconds: float = 0.0
    max_failure_cycles: int = 0
    max_task_failure_rounds: int = 3
    max_task_total_failure_rounds: int = 6
    max_task_typescript_quality_rounds: int = 3
    result_log_path: Optional[Path] = None
    accepted_work_log_path: Optional[Path] = Path("docs/IPFS_DATASETS_LOGIC_PORT_DAEMON_ACCEPTED.md")
    accepted_work_artifact_dir: Optional[Path] = Path("ipfs_datasets_py/.daemon/accepted-work")
    codex_trace_dir: Optional[Path] = Path("ipfs_datasets_py/.daemon/codex-runs")
    failed_patch_dir: Path = Path("ipfs_datasets_py/.daemon/failed-patches")
    status_path: Optional[Path] = Path("ipfs_datasets_py/.daemon/logic-port-daemon.status.json")
    progress_path: Optional[Path] = Path("ipfs_datasets_py/.daemon/logic-port-daemon.progress.json")
    heartbeat_interval_seconds: float = 30.0
    patch_repair_attempts: int = 1
    file_repair_attempts: int = 1
    preflight_repair_attempts: int = 1
    validation_repair_attempts: int = 1
    validation_repair_failure_budget: int = 2
    auto_commit: bool = False
    auto_commit_branch: str = "main"
    auto_commit_startup_dirty: bool = False
    proposal_attempts: int = 3
    prefer_file_edits: bool = True
    task_board_doc: Optional[Path] = Path("docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md")
    update_task_board: bool = True
    revisit_blocked_tasks: bool = False
    blocked_backlog_limit: int = 10
    blocked_task_strategy: str = "plan-order"
    replenish_plan_when_empty: bool = True
    plan_replenishment_limit: int = 12

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path

    def proposal_transport_mode(self) -> str:
        """Return normalized proposal transport mode."""

        mode = str(self.proposal_transport or "llm_router").strip().lower()
        aliases = {
            "auto": "worktree",
            "router": "llm_router",
            "router-json": "llm_router",
            "router_json": "llm_router",
            "json": "llm_router",
            "patch": "llm_router",
            "direct": "worktree",
            "direct_edit": "worktree",
            "direct-edit": "worktree",
            "patchless": "worktree",
            "worktree_edit": "worktree",
            "worktree-edit": "worktree",
        }
        mode = aliases.get(mode, mode)
        if mode not in {"llm_router", "hybrid", "worktree"}:
            return "llm_router"
        return mode

    def resolved_worktree_root(self) -> Path:
        return self.resolve(self.worktree_root)


@dataclass
class LogicPortArtifact:
    """Patch proposal plus validation state for one daemon iteration."""

    summary: str = ""
    patch: str = ""
    tasks: List[str] = field(default_factory=list)
    files: List[Dict[str, str]] = field(default_factory=list)
    validation_commands: List[List[str]] = field(default_factory=list)
    raw_response: str = ""
    target_task: str = ""
    impact: str = ""
    applied: bool = False
    dry_run: bool = True
    validation_results: List[CommandResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    failure_kind: str = ""
    proposal_transport: str = ""

    @property
    def validation_passed(self) -> bool:
        return bool(self.validation_results) and all(result.ok for result in self.validation_results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "target_task": self.target_task,
            "impact": self.impact,
            "tasks": self.tasks,
            "has_patch": bool(self.patch.strip() and self.proposal_transport != "worktree"),
            "has_audit_diff": bool(self.patch.strip()),
            "uses_worktree_transport": self.proposal_transport == "worktree",
            "files": [item.get("path", "") for item in self.files],
            "applied": self.applied,
            "dry_run": self.dry_run,
            "validation_passed": self.validation_passed,
            "validation_results": [result.compact() for result in self.validation_results],
            "errors": self.errors,
            "changed_files": self.changed_files,
            "failure_kind": self.failure_kind,
            "proposal_transport": self.proposal_transport,
            "raw_response_prefix": self.raw_response[:2000] if self.raw_response else "",
        }


def _read_text(path: Path, *, limit: Optional[int] = None) -> str:
    return _shared_read_text(path, limit=limit)


def _truncate_text(text: str, *, limit: Optional[int]) -> str:
    return _shared_truncate_text(text, limit=limit)


def _focused_task_board_excerpt(markdown: str, selected_task: Optional[PlanTask], *, limit: int) -> str:
    return _shared_focused_task_board_excerpt(markdown, selected_task, limit=limit)


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    return _shared_extract_json_object(text)


def _extract_codex_event_text_candidates(text: str) -> List[str]:
    """Extract assistant text candidates from Codex JSONL event streams."""

    return _shared_extract_codex_event_text_candidates(text)


def _extract_text_from_codex_event_object(value: Any) -> str:
    return _shared_extract_text_from_codex_event_object(value)


def _looks_like_empty_codex_event_stream(text: str) -> bool:
    return _shared_looks_like_empty_codex_event_stream(text)


def parse_llm_patch_response(text: str) -> LogicPortArtifact:
    """Parse a model response into a patch artifact.

    Preferred response format is JSON with ``summary`` and ``patch`` fields.
    A fenced diff block is accepted as a fallback to make manual testing easy.
    """

    parsed = _extract_json_object(text)
    if parsed is not None:
        return LogicPortArtifact(
            summary=str(parsed.get("summary", "")),
            impact=str(parsed.get("impact", "")),
            patch=str(parsed.get("patch", "")),
            files=_parse_file_edits(parsed.get("files", [])),
            tasks=_shared_normalize_task_references(parsed.get("tasks", [])),
            validation_commands=_shared_normalize_validation_commands(parsed.get("validation_commands", [])),
            raw_response=text,
        )

    diff_match = DIFF_BLOCK_RE.search(text)
    if diff_match:
        return LogicPortArtifact(summary="Patch extracted from fenced diff block.", patch=diff_match.group(1), raw_response=text)

    if _looks_like_empty_codex_event_stream(text):
        return LogicPortArtifact(
            raw_response=text,
            errors=["Codex returned JSONL startup events without an assistant proposal."],
            failure_kind="codex_empty_event_stream",
        )

    return LogicPortArtifact(raw_response=text, errors=["LLM response did not contain JSON or a fenced diff patch."])


def _parse_file_edits(value: Any) -> List[Dict[str, str]]:
    return _shared_normalize_file_edits(value)


def _repair_common_typescript_text_damage(content: str) -> str:
    return _shared_repair_common_typescript_text_damage(content)


def _repair_common_typescript_file_edits(edits: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    return _shared_repair_common_typescript_file_edits(edits)


def _obvious_typescript_text_damage(content: str) -> List[str]:
    return _shared_obvious_typescript_text_damage(content)


def _read_daemon_results(path: Path) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    return _shared_read_daemon_results(path)


def _normalize_task_label(value: str) -> str:
    return _shared_normalize_task_label(value)


def _same_task_label(left: str, right: str) -> bool:
    return _shared_same_task_label(left, right)


def _recent_failure_count(rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]], task_label: str, failure_kind: str) -> int:
    return _shared_recent_failure_count(
        rows,
        task_label,
        failure_kind,
        classify_failure_kind=_classify_failure_kind,
    )


def _recent_total_failure_count(rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]], task_label: str) -> int:
    return _shared_recent_total_failure_count(rows, task_label)


def _recent_rollback_quality_failure_count(rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]], task_label: str) -> int:
    return _shared_recent_rollback_failure_count(
        rows,
        task_label,
        classify_failure_kind=_classify_failure_kind,
        rollback_failure_kinds=ROLLBACK_QUALITY_FAILURE_KINDS,
    )


def _current_task_failure_counts(
    rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]],
    task_label: str,
) -> Dict[str, Any]:
    return _shared_current_task_failure_counts(
        rows,
        task_label,
        classify_failure_kind=_classify_failure_kind,
    )


def _rounds_since_last_valid(rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]]) -> int:
    return _shared_rounds_since_last_valid(rows)


def _last_task_attempt_index(rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]], task_label: str) -> int:
    return _shared_last_task_attempt_index(rows, task_label)



def _task_failure_summary(
    rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]],
    task_label: str,
) -> Dict[str, Any]:
    return _shared_task_failure_summary(
        rows,
        task_label,
        classify_failure_kind=_classify_failure_kind,
        compact=lambda value, limit: _compact_message(value, limit=limit),
    )


def _patch_changed_files(patch: str) -> List[str]:
    return _shared_paths_from_unified_diff(patch)


def _git_status_paths(stdout: str) -> List[str]:
    """Return paths from ``git status --porcelain`` output."""

    return _shared_git_status_paths(stdout)


def _untracked_paths_from_git_status(stdout: str) -> List[str]:
    return _shared_untracked_paths_from_git_status(stdout)


def _git_worktree_paths_from_porcelain(stdout: str) -> List[Path]:
    """Return registered Git worktree paths from porcelain output."""

    return _shared_git_worktree_paths_from_porcelain(stdout)


def _pid_is_alive(pid: int) -> bool:
    return _shared_pid_is_alive(pid)


def _pid_command_line(pid: int) -> str:
    return _shared_pid_command_line(pid)


def _pid_looks_like_logic_port_owner(pid: int, *, repo_root: Path, worktree_path: Path) -> bool:
    return _shared_pid_looks_like_worktree_owner(
        pid,
        repo_root=repo_root,
        worktree_path=worktree_path,
        daemon_process_fragment="ipfs_datasets_py.optimizers.logic_port_daemon",
    )


def _owner_pid_from_worktree(path: Path, owner: Dict[str, Any]) -> Optional[int]:
    return _shared_owner_pid_from_worktree(path, owner)


def _artifact_paths(artifact: LogicPortArtifact) -> List[str]:
    return _shared_paths_from_patch_and_file_edits(artifact.patch, artifact.files)


def _task_allows_non_runtime_only(task: Optional[PlanTask]) -> bool:
    return _shared_task_title_contains_any(task, NON_RUNTIME_TASK_KEYWORDS)


def _task_requires_fixture_validation(task: Optional[PlanTask]) -> bool:
    return _shared_task_title_contains_any(task, FIXTURE_VALIDATION_TASK_KEYWORDS)


def _task_is_explicit_failure(task: Optional[PlanTask]) -> bool:
    if task is None:
        return False
    title = task.title.lower()
    return "latest daemon round failed" in title or "blocked or failing" in title


def _task_tokens(task: Optional[PlanTask]) -> List[str]:
    return _shared_task_title_tokens(task)


def _rank_relevant_file(path: str, tokens: Sequence[str]) -> int:
    return _shared_rank_relevant_context_file(
        path,
        tokens,
        preferred_path_fragments=("/cec/", "/tdfol/", "/fol/", "/deontic/"),
    )


def _compact_message(value: Any, *, limit: int = 600) -> str:
    return _shared_compact_message(value, limit=limit)


def _classify_failure_kind(artifact: Dict[str, Any]) -> str:
    explicit = str(artifact.get("failure_kind") or "")
    errors = " ".join(str(error) for error in artifact.get("errors", []) if error)
    validation = artifact.get("validation_results", [])
    validation_text = errors
    if isinstance(validation, list):
        for item in validation:
            if isinstance(item, dict):
                validation_text += " " + str(item.get("stdout", "")) + " " + str(item.get("stderr", ""))
    lower = validation_text.lower()
    if _has_typescript_quality_diagnostics(validation_text):
        return "typescript_quality"
    if explicit:
        return explicit
    if "cloudflare" in lower or "403 forbidden" in lower or "plugins/featured" in lower or "analytics-events" in lower:
        return "provider_http_403"
    if "timed out" in lower:
        return "timeout"
    if "did not contain json" in lower:
        return "parse"
    if "ts1005" in lower or "ts" in lower and "error" in lower:
        return "validation"
    return "invalid_no_change"


def _has_typescript_quality_diagnostics(text: str) -> bool:
    return _shared_has_diagnostic_codes(text, TYPESCRIPT_QUALITY_ERROR_CODES)


def _typescript_diagnostic_signatures(text: str) -> List[str]:
    """Return stable diagnostic families for repeated TypeScript failure loops."""

    return [signature for signature in _shared_diagnostic_signatures(text) if signature.startswith("TS")]


def _artifact_validation_text(artifact: Dict[str, Any]) -> str:
    return _shared_artifact_validation_text(artifact)


def _typescript_quality_failure_counts(rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]]) -> Dict[str, Any]:
    return _shared_quality_failure_counts(
        rows,
        classify_failure_kind=_classify_failure_kind,
        quality_failure_kind="typescript_quality",
        signature_extractor=_typescript_diagnostic_signatures,
        validation_text_extractor=_artifact_validation_text,
    )


def _rollback_quality_failure_counts(rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]]) -> Dict[str, Any]:
    return _shared_rollback_failure_counts(
        rows,
        classify_failure_kind=_classify_failure_kind,
        rollback_failure_kinds=ROLLBACK_QUALITY_FAILURE_KINDS,
    )


def _has_runtime_logic_change(paths: Sequence[str]) -> bool:
    return _shared_paths_include_required_change(
        paths,
        prefixes=(RUNTIME_LOGIC_PREFIX,),
        excluded_prefixes=(PARITY_FIXTURE_PREFIX,),
    )


def _has_logic_test_change(paths: Sequence[str]) -> bool:
    return _shared_paths_include_required_change(
        paths,
        prefixes=(RUNTIME_LOGIC_PREFIX,),
        suffixes=(".test.ts",),
    )


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    stdin: Optional[str] = None,
) -> CommandResult:
    return _shared_run_command(
        command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        stdin=stdin,
    )


class LogicPortDaemonOptimizer(BaseOptimizer):
    """Optimizer-backed daemon that asks an LLM for safe repository patches."""

    def __init__(
        self,
        daemon_config: Optional[LogicPortDaemonConfig] = None,
        *,
        llm_router: Optional[Any] = None,
        optimizer_config: Optional[OptimizerConfig] = None,
    ) -> None:
        daemon_config = daemon_config or LogicPortDaemonConfig()
        base_config = optimizer_config or OptimizerConfig(
            max_iterations=daemon_config.max_iterations,
            target_score=daemon_config.target_score,
            validation_enabled=True,
            early_stopping=False,
        )
        super().__init__(config=base_config, llm_backend=llm_router)
        self.daemon_config = daemon_config
        self.llm_router = llm_router
        self._status_lock = threading.Lock()
        self._last_status_payload: Dict[str, Any] = {}

    def generate(self, input_data: Any, context: OptimizationContext) -> LogicPortArtifact:
        transport_mode = self.daemon_config.proposal_transport_mode()
        if transport_mode == "worktree":
            return self._generate_worktree_artifact(input_data=input_data, context=context)
        if transport_mode == "hybrid":
            worktree_artifact = self._generate_worktree_artifact(input_data=input_data, context=context)
            if (worktree_artifact.files or worktree_artifact.patch.strip()) and not worktree_artifact.errors:
                return worktree_artifact
            self._write_status(
                "worktree_proposal_fallback_to_router",
                artifact=worktree_artifact.to_dict(),
                selected_task=worktree_artifact.target_task,
            )

        prompt = self._build_prompt(input_data=input_data, context=context)
        selected_task = self._current_plan_task()
        target_label = selected_task.label if selected_task else ""
        attempts = max(1, int(self.daemon_config.proposal_attempts))
        previous_feedback = ""
        artifact = LogicPortArtifact(summary="No proposal generated.")
        for attempt in range(1, attempts + 1):
            attempt_prompt = prompt if attempt == 1 else self._build_retry_prompt(prompt, previous_feedback, attempt=attempt, attempts=attempts)
            self._write_status("proposal_attempt_started", attempt=attempt, attempts=attempts, selected_task=target_label)
            response = self._call_llm(attempt_prompt)
            artifact = parse_llm_patch_response(response)
            artifact.dry_run = self.daemon_config.dry_run
            artifact.target_task = target_label
            artifact.proposal_transport = "llm_router"
            if artifact.files:
                artifact.files = _repair_common_typescript_file_edits(artifact.files)
            preflight_errors = self._preflight_artifact(artifact, selected_task=selected_task)
            if artifact.files:
                preflight_errors.extend(self._typescript_replacement_preflight_errors(artifact.files))
            if preflight_errors:
                repaired = self._repair_file_edits_after_preflight(
                    artifact,
                    preflight_errors,
                    context=context,
                    selected_task=selected_task,
                )
                if repaired.files:
                    repaired.files = _repair_common_typescript_file_edits(repaired.files)
                    repaired_errors = self._preflight_artifact(repaired, selected_task=selected_task)
                    repaired_errors.extend(self._typescript_replacement_preflight_errors(repaired.files))
                    if not repaired_errors:
                        repaired.dry_run = self.daemon_config.dry_run
                        repaired.target_task = target_label
                        return repaired
                    artifact.errors.append(
                        "Preflight repair still produced rejected TypeScript replacements:\n"
                        + "\n".join(repaired_errors)
                    )
                artifact.errors.extend(preflight_errors)
                artifact.failure_kind = "preflight"
                previous_feedback = self._proposal_feedback(artifact)
                self._write_status(
                    "proposal_attempt_rejected",
                    attempt=attempt,
                    attempts=attempts,
                    selected_task=target_label,
                    artifact=artifact.to_dict(),
                )
                continue
            if artifact.files or artifact.patch.strip():
                return artifact
            artifact.failure_kind = artifact.failure_kind or ("parse" if artifact.errors else "empty_proposal")
            previous_feedback = self._proposal_feedback(artifact)
            self._write_status(
                "proposal_attempt_rejected",
                attempt=attempt,
                attempts=attempts,
                selected_task=target_label,
                artifact=artifact.to_dict(),
            )
        return artifact

    def _generate_worktree_artifact(self, *, input_data: Any, context: OptimizationContext) -> LogicPortArtifact:
        selected_task = self._current_plan_task()
        target_label = selected_task.label if selected_task else ""
        attempts = max(1, int(self.daemon_config.proposal_attempts))
        artifact = LogicPortArtifact(summary="No worktree proposal generated.", target_task=target_label)
        previous_feedback = ""

        for attempt in range(1, attempts + 1):
            self._write_status(
                "requesting_worktree_edit",
                attempt=attempt,
                attempts=attempts,
                selected_task=target_label,
                timeout_seconds=self.daemon_config.worktree_edit_timeout_seconds,
                worktree_root=str(self.daemon_config.resolved_worktree_root()),
            )
            artifact = self._request_worktree_edit_artifact(
                input_data=input_data,
                context=context,
                attempt=attempt,
                attempts=attempts,
                previous_feedback=previous_feedback,
            )
            artifact.dry_run = self.daemon_config.dry_run
            artifact.target_task = target_label
            artifact.proposal_transport = "worktree"
            if artifact.files:
                artifact.files = _repair_common_typescript_file_edits(artifact.files)

            preflight_errors = self._preflight_artifact(artifact, selected_task=selected_task)
            if artifact.files:
                preflight_errors.extend(self._typescript_replacement_preflight_errors(artifact.files))
            if preflight_errors:
                artifact.errors.extend(preflight_errors)
                artifact.failure_kind = artifact.failure_kind or "preflight"
                previous_feedback = self._proposal_feedback(artifact)
                self._write_status(
                    "worktree_proposal_rejected",
                    attempt=attempt,
                    attempts=attempts,
                    selected_task=target_label,
                    artifact=artifact.to_dict(),
                )
                continue
            if artifact.files or artifact.patch.strip():
                return artifact

            artifact.failure_kind = artifact.failure_kind or ("parse" if artifact.errors else "empty_proposal")
            previous_feedback = self._proposal_feedback(artifact)
            self._write_status(
                "worktree_proposal_rejected",
                attempt=attempt,
                attempts=attempts,
                selected_task=target_label,
                artifact=artifact.to_dict(),
            )
        return artifact

    def _request_worktree_edit_artifact(
        self,
        *,
        input_data: Any,
        context: OptimizationContext,
        attempt: int,
        attempts: int,
        previous_feedback: str,
    ) -> LogicPortArtifact:
        repo_root = self.daemon_config.repo_root
        worktree_root = self.daemon_config.resolved_worktree_root()
        cleanup_result = self.cleanup_stale_worktrees()
        worktree_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        worktree_path = worktree_root / f"cycle_{attempt:02d}_{stamp}_{os.getpid()}"
        metadata_rel = ".logic_port_worktree_proposal.json"
        owner_rel = ".logic_port_worktree_owner.json"
        raw_trace: Dict[str, Any] = {
            "transport": "worktree",
            "attempt": attempt,
            "attempts": attempts,
            "worktree_path": str(worktree_path),
            "metadata_path": metadata_rel,
            "owner_path": owner_rel,
            "cleanup_before_create": cleanup_result,
        }

        try:
            add_result = run_command(
                ("git", "worktree", "add", "--detach", str(worktree_path), "HEAD"),
                cwd=repo_root,
                timeout_seconds=60,
            )
            raw_trace["worktree_add"] = add_result.compact(limit=12000)
            if not add_result.ok:
                return LogicPortArtifact(
                    summary="Worktree proposal failed before Codex edit.",
                    raw_response=json.dumps(raw_trace, indent=2, default=str),
                    errors=["git worktree add failed: " + (add_result.stderr or add_result.stdout).strip()[:1000]],
                    failure_kind="worktree_add",
                    proposal_transport="worktree",
                )

            self._write_worktree_owner_file(worktree_path / owner_rel, attempt=attempt)
            prompt = self._build_worktree_edit_prompt(
                input_data=input_data,
                context=context,
                metadata_rel=metadata_rel,
                attempt=attempt,
                attempts=attempts,
                previous_feedback=previous_feedback,
            )
            codex_result = run_command(
                (
                    self.daemon_config.codex_bin,
                    "exec",
                    "--skip-git-repo-check",
                    "--sandbox",
                    self.daemon_config.worktree_codex_sandbox,
                    "-m",
                    self.daemon_config.model_name,
                    "-C",
                    str(worktree_path),
                    "-",
                ),
                cwd=worktree_path,
                stdin=prompt,
                timeout_seconds=max(1, int(self.daemon_config.worktree_edit_timeout_seconds)),
            )
            raw_trace["codex_exec"] = codex_result.compact(limit=20000)

            full_status = run_command(
                ("git", "status", "--porcelain"),
                cwd=worktree_path,
                timeout_seconds=60,
            )
            raw_trace["full_status"] = full_status.compact(limit=12000)
            disallowed_paths = self._disallowed_worktree_paths(
                _git_status_paths(full_status.stdout),
                metadata_rel=metadata_rel,
                owner_rel=owner_rel,
            )
            if disallowed_paths:
                raw_trace["disallowed_paths"] = disallowed_paths
                return LogicPortArtifact(
                    summary="Worktree proposal edited paths outside the logic-port allowlist.",
                    raw_response=json.dumps(raw_trace, indent=2, default=str),
                    errors=["Worktree proposal edited disallowed paths: " + ", ".join(disallowed_paths[:12])],
                    failure_kind="worktree_disallowed_paths",
                    proposal_transport="worktree",
                )

            diff_paths = self._worktree_diff_paths()
            status_result = run_command(
                ("git", "status", "--porcelain", "--", *diff_paths),
                cwd=worktree_path,
                timeout_seconds=60,
            )
            raw_trace["status"] = status_result.compact(limit=12000)
            untracked_paths = _untracked_paths_from_git_status(status_result.stdout)
            raw_trace["untracked_paths"] = untracked_paths
            if untracked_paths:
                add_intent = run_command(
                    ("git", "add", "-N", "--", *untracked_paths),
                    cwd=worktree_path,
                    timeout_seconds=60,
                )
                raw_trace["git_add_intent_to_add"] = add_intent.compact(limit=12000)

            diff_result = run_command(
                ("git", "diff", "--binary", "--", *diff_paths),
                cwd=worktree_path,
                timeout_seconds=60,
            )
            raw_trace["git_diff"] = diff_result.compact(limit=20000)
            patch = diff_result.stdout if diff_result.ok else ""
            metadata = self._read_worktree_metadata(worktree_path / metadata_rel)
            raw_trace["metadata"] = metadata
            changed_files = _patch_changed_files(patch)
            if not changed_files:
                changed_files = [
                    str(path)
                    for path in metadata.get("changed_files", [])
                    if isinstance(path, str) and path.strip()
                ] if isinstance(metadata.get("changed_files"), list) else []
            files = self._worktree_file_edits(worktree_path, changed_files)
            validation_commands = [
                [str(part) for part in command]
                for command in metadata.get("validation_commands", [])
                if isinstance(command, list) and all(isinstance(part, str) for part in command)
            ] if isinstance(metadata.get("validation_commands"), list) else []
            tasks = [
                str(item)
                for item in metadata.get("tasks", [])
                if isinstance(item, (str, int, float)) and str(item).strip()
            ] if isinstance(metadata.get("tasks"), list) else []

            errors: List[str] = []
            failure_kind = ""
            if not patch.strip() and not files:
                reason = "worktree edit produced no allowed TypeScript port changes"
                if not codex_result.ok:
                    reason = "worktree edit command failed without producing allowed changes: " + (
                        codex_result.stderr or codex_result.stdout
                    ).strip()[:1000]
                    failure_kind = "worktree_codex_failed"
                errors.append(reason)
                failure_kind = failure_kind or "worktree_no_change"
            selected_task = self._current_plan_task()

            return LogicPortArtifact(
                summary=str(metadata.get("summary") or "Worktree direct-edit proposal."),
                impact=str(metadata.get("impact") or "Git harvested the isolated-worktree edits for validation."),
                patch=patch,
                files=files,
                tasks=tasks or ([selected_task.label] if selected_task else []),
                validation_commands=validation_commands,
                raw_response=json.dumps(raw_trace, indent=2, default=str),
                errors=errors,
                failure_kind=failure_kind,
                changed_files=changed_files,
                proposal_transport="worktree",
            )
        finally:
            remove_result = run_command(
                ("git", "worktree", "remove", "--force", str(worktree_path)),
                cwd=repo_root,
                timeout_seconds=60,
            )
            if not remove_result.ok and worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
            run_command(
                ("git", "worktree", "prune", "--expire", "now"),
                cwd=repo_root,
                timeout_seconds=60,
            )

    def critique(self, artifact: LogicPortArtifact, context: OptimizationContext) -> Tuple[float, List[str]]:
        feedback: List[str] = []
        score = 0.0

        if artifact.errors:
            feedback.extend(artifact.errors)
        if artifact.patch.strip():
            score += 0.25
        else:
            feedback.append("No patch was proposed.")
        if artifact.applied or artifact.dry_run:
            score += 0.25
        else:
            feedback.append("Patch was not applied.")
        if artifact.validation_results:
            passed = sum(1 for result in artifact.validation_results if result.ok)
            score += 0.5 * (passed / len(artifact.validation_results))
            for result in artifact.validation_results:
                if not result.ok:
                    feedback.append(f"Validation failed: {' '.join(result.command)}")
        else:
            feedback.append("Validation has not run yet.")

        return min(score, 1.0), feedback

    def _proposal_feedback(self, artifact: LogicPortArtifact) -> str:
        diagnostic_context = self._typescript_diagnostic_context(artifact)
        parts = [
            f"summary={artifact.summary or '<empty>'}",
            f"failure_kind={artifact.failure_kind or '<empty>'}",
            f"errors={'; '.join(artifact.errors[:3]) if artifact.errors else '<none>'}",
            f"typescript_diagnostic_context={diagnostic_context or '<none>'}",
            f"response_prefix={artifact.raw_response[:1200]}",
        ]
        return "\n".join(parts)

    def _typescript_diagnostic_context(self, artifact: LogicPortArtifact, *, radius: int = 2, limit: int = 6000) -> str:
        """Render failing replacement lines around TypeScript diagnostics for retry prompts."""

        if not artifact.files or not artifact.errors:
            return ""
        edits_by_path = _shared_file_edits_by_path(artifact.files)
        if not edits_by_path:
            return ""
        return self._render_typescript_diagnostic_context(
            "\n".join(str(error) for error in artifact.errors),
            edits_by_path,
            radius=radius,
            limit=limit,
        )

    def _render_typescript_diagnostic_context(
        self,
        text: str,
        edits_by_path: Dict[str, str],
        *,
        radius: int = 2,
        limit: int = 6000,
    ) -> str:
        return _shared_render_typescript_diagnostic_context(
            text,
            edits_by_path,
            radius=radius,
            limit=limit,
        )

    @staticmethod
    def _match_diagnostic_edit_path(diagnostic_path: str, edits_by_path: Dict[str, str]) -> Optional[str]:
        return _shared_match_diagnostic_edit_path(diagnostic_path, edits_by_path)

    def _build_retry_prompt(self, original_prompt: str, previous_feedback: str, *, attempt: int, attempts: int) -> str:
        return f"""{original_prompt}

Previous proposal attempt {attempt - 1} of {attempts} was rejected before any files could be used by the daemon.

Rejection details:
{previous_feedback}

Critical correction for attempt {attempt}:
- Return ONLY one JSON object. No markdown fence, no explanation before or after it.
- Use the `files` array with complete replacement file contents.
- Leave `patch` as an empty string.
- The Codex subprocess may be read-only, but the daemon itself applies the returned `files` contents after validation. Do not refuse because of a read-only sandbox.
- Include at least one changed source/test file that will be used by `npm run validate:logic-port`.
- Do not use bare TypeScript generic aliases. Always spell `Record<string, unknown>`, `Promise<ResultType>`, `Omit<Type, Keys>`, `Map<Key, Value>`, and `Array<Item>` with every required type argument.
- For loop and comparison expressions must use complete operators such as `<`, `<=`, `>`, `>=`, `===`, and `!==`; never omit the operator around bounds checks.
- Before returning JSON, inspect the replacement contents for stripped operators or generic arguments such as `index  items.length`, `arity  'Entity'`, `Record =`, `Array =`, `Promise;`, or `Omit;`. If you find one, simplify that block into explicit guards or named interfaces before returning.
- Preserve public exports already present in the replaced module unless the selected task explicitly removes them.
- Do not describe a plan, mention inability to edit files, or return status text. The entire response must parse as JSON.
- If the previous response was prose, convert that intent into complete file replacements now.
"""

    def optimize(
        self,
        artifact: LogicPortArtifact,
        score: float,
        feedback: List[str],
        context: OptimizationContext,
    ) -> LogicPortArtifact:
        if not artifact.patch.strip() and not artifact.files:
            if not artifact.failure_kind:
                artifact.failure_kind = "parse" if artifact.errors else "empty_proposal"
            if not artifact.errors:
                artifact.errors.append("No usable patch or file replacement was proposed.")
            return artifact

        if artifact.errors and artifact.failure_kind in {"preflight", "validation_repair_preflight", "file_repair_preflight"}:
            return artifact

        if self.daemon_config.dry_run:
            artifact.validation_results = self._run_validation()
            return artifact

        if artifact.files:
            artifact.files = _repair_common_typescript_file_edits(artifact.files)
        preflight_errors = self._preflight_artifact(artifact, selected_task=self._current_plan_task())
        if artifact.files:
            preflight_errors.extend(self._typescript_replacement_preflight_errors(artifact.files))
        if preflight_errors:
            artifact.errors.extend(preflight_errors)
            artifact.failure_kind = "preflight"
            return artifact

        dirty_errors = self._dirty_touched_file_errors(_artifact_paths(artifact))
        if dirty_errors:
            self._auto_commit_paths(
                _artifact_paths(artifact),
                reason="dirty touched files before applying candidate",
                target_task=artifact.target_task,
                summary=artifact.summary,
            )
            dirty_errors = self._dirty_touched_file_errors(_artifact_paths(artifact))
        if dirty_errors:
            artifact.errors.extend(dirty_errors)
            artifact.failure_kind = "dirty_touched_files"
            return artifact

        if artifact.files:
            try:
                artifact.applied, artifact.validation_results, changed_files = self._apply_file_edits_with_validation(artifact.files)
            except Exception as exc:
                artifact.errors.append(str(exc))
                artifact.failure_kind = "file_edit_exception"
                return artifact
            if not artifact.applied:
                if not changed_files and all(result.ok for result in artifact.validation_results):
                    artifact.errors.append("File edits made no content changes.")
                    artifact.failure_kind = "no_change"
                else:
                    repaired = (
                        self._repair_worktree_file_edits_after_validation(artifact, context=context)
                        if artifact.proposal_transport == "worktree"
                        else LogicPortArtifact(raw_response=artifact.raw_response)
                    )
                    if not repaired.files:
                        repaired = self._repair_file_edits_after_validation(artifact, context=context)
                    if repaired.files:
                        repaired.proposal_transport = repaired.proposal_transport or artifact.proposal_transport
                        repaired.files = _repair_common_typescript_file_edits(repaired.files)
                        preflight_errors = self._preflight_artifact(repaired, selected_task=self._current_plan_task())
                        preflight_errors.extend(self._typescript_replacement_preflight_errors(repaired.files))
                        if preflight_errors:
                            artifact.errors.extend(preflight_errors)
                            artifact.failure_kind = "validation_repair_preflight"
                            return artifact
                        try:
                            applied, validation_results, changed_files = self._apply_file_edits_with_validation(repaired.files)
                        except Exception as exc:
                            artifact.errors.append(str(exc))
                            artifact.failure_kind = "validation_repair_exception"
                            return artifact
                        artifact.files = repaired.files
                        artifact.summary = repaired.summary or artifact.summary
                        artifact.impact = repaired.impact or artifact.impact
                        artifact.validation_results = validation_results
                        artifact.applied = applied
                        artifact.changed_files = changed_files if applied else []
                        if applied:
                            artifact.failure_kind = ""
                            artifact.errors = []
                            return artifact
                        artifact.failure_kind = _classify_failure_kind(artifact.to_dict()) if _classify_failure_kind(artifact.to_dict()) == "typescript_quality" else "validation_repair"
                    artifact.errors.append("File edits failed validation and were rolled back.")
                    if not artifact.failure_kind:
                        artifact.failure_kind = _classify_failure_kind(artifact.to_dict())
                        if artifact.failure_kind == "invalid_no_change":
                            artifact.failure_kind = "validation"
            else:
                artifact.changed_files = changed_files
            return artifact

        if not artifact.patch.strip():
            if not artifact.failure_kind:
                artifact.failure_kind = "empty_proposal"
            return artifact

        check = run_command(
            ("git", "apply", "--check", "-"),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=self.daemon_config.command_timeout_seconds,
            stdin=artifact.patch,
        )
        if not check.ok:
            self._persist_failed_patch(artifact.patch, check, context=context)
            repaired = self._repair_patch(artifact.patch, check, context=context)
            if repaired.strip() and repaired != artifact.patch:
                artifact.patch = repaired
                check = run_command(
                    ("git", "apply", "--check", "-"),
                    cwd=self.daemon_config.repo_root,
                    timeout_seconds=self.daemon_config.command_timeout_seconds,
                    stdin=artifact.patch,
                )
                if not check.ok:
                    self._persist_failed_patch(artifact.patch, check, context=context)
            if not check.ok:
                file_repair = self._repair_patch_as_files(artifact, check, context=context)
                if file_repair.files:
                    file_repair.files = _repair_common_typescript_file_edits(file_repair.files)
                    preflight_errors = self._preflight_artifact(file_repair, selected_task=self._current_plan_task())
                    if preflight_errors:
                        artifact.errors.extend(preflight_errors)
                        artifact.failure_kind = "file_repair_preflight"
                        artifact.validation_results.append(check)
                        return artifact
                    try:
                        applied, validation_results, changed_files = self._apply_file_edits_with_validation(file_repair.files)
                    except Exception as exc:
                        artifact.errors.append(str(exc))
                        artifact.failure_kind = "file_repair"
                        artifact.validation_results.append(check)
                        return artifact
                    artifact.files = file_repair.files
                    artifact.patch = ""
                    artifact.validation_results = validation_results
                    artifact.applied = applied
                    artifact.summary = file_repair.summary or artifact.summary
                    artifact.impact = file_repair.impact or artifact.impact
                    artifact.changed_files = changed_files if applied else []
                    if applied:
                        return artifact
                    if not changed_files and all(result.ok for result in validation_results):
                        artifact.errors.append("Patch-to-file repair made no content changes.")
                        artifact.failure_kind = "file_repair_no_change"
                    else:
                        artifact.errors.append("Patch-to-file repair failed validation and was rolled back.")
                        artifact.failure_kind = "file_repair_validation"
                    return artifact
                artifact.errors.append("Patch failed git apply --check.")
                artifact.failure_kind = "apply_check"
                artifact.validation_results.append(check)
                return artifact

        applied = run_command(
            ("git", "apply", "-"),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=self.daemon_config.command_timeout_seconds,
            stdin=artifact.patch,
        )
        artifact.validation_results.append(applied)
        artifact.applied = applied.ok
        if not applied.ok:
            artifact.errors.append("Patch failed git apply.")
            artifact.failure_kind = "apply"
            return artifact

        artifact.validation_results.extend(self._run_validation())
        if not artifact.validation_passed:
            rolled_back = self._rollback_patch(artifact.patch)
            artifact.validation_results.extend(rolled_back)
            if all(result.ok for result in rolled_back):
                artifact.applied = False
                artifact.errors.append("Patch failed validation and was rolled back.")
                artifact.failure_kind = "validation"
            else:
                artifact.errors.append("Patch failed validation and automatic rollback failed.")
                artifact.failure_kind = "rollback"
        else:
            artifact.changed_files = _patch_changed_files(artifact.patch)
        return artifact

    def validate(self, artifact: LogicPortArtifact, context: OptimizationContext) -> bool:
        if artifact.dry_run:
            return (bool(artifact.patch.strip()) or bool(artifact.files)) and not artifact.errors
        if artifact.files:
            return artifact.applied and not artifact.errors
        return artifact.applied and artifact.validation_passed and not artifact.errors

    def run_once(self, *, session_id: Optional[str] = None) -> Dict[str, Any]:
        session_id = session_id or f"logic-port-{uuid.uuid4()}"
        context = OptimizationContext(
            session_id=session_id,
            input_data={},
            domain="logic-port",
            constraints={
                "model_name": self.daemon_config.model_name,
                "dry_run": self.daemon_config.dry_run,
                "proposal_transport": self.daemon_config.proposal_transport_mode(),
            },
        )
        result = self.run_session({}, context)
        artifact = result.get("artifact")
        if isinstance(artifact, LogicPortArtifact):
            result["artifact"] = artifact.to_dict()
        return dict(result)

    def run_daemon(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        session_id = f"logic-port-daemon-{uuid.uuid4()}"
        heartbeat_stop, heartbeat_thread = self._start_status_heartbeat()
        selected_task = self._current_plan_task()
        self._write_status(
            "session_started",
            session_id=session_id,
            selected_task=selected_task.label if selected_task else "",
        )
        log_session_start(
            LOGGER,
            session_id=session_id,
            domain="logic-port",
            input_size=sum(
                len(_read_text(self.daemon_config.resolve(path)))
                for path in [*self.daemon_config.plan_docs, *self.daemon_config.status_docs]
                if self.daemon_config.resolve(path).exists()
            ),
            config={
                "model_name": self.daemon_config.model_name,
                "max_iterations": self.daemon_config.max_iterations,
                "dry_run": self.daemon_config.dry_run,
                "proposal_transport": self.daemon_config.proposal_transport_mode(),
            },
            component=self.__class__.__name__,
        )
        started = time.time()

        try:
            terminal_result = self._no_eligible_task_result()
            if terminal_result is not None:
                results.append(terminal_result)
                self._write_status(
                    "no_eligible_tasks",
                    session_id=session_id,
                    artifact=terminal_result.get("artifact", {}),
                )
                return results

            for iteration in range(self.daemon_config.max_iterations):
                iteration_started = time.time()
                selected_task = self._current_plan_task()
                self._write_status(
                    "iteration_started",
                    session_id=session_id,
                    iteration=iteration + 1,
                    selected_task=selected_task.label if selected_task else "",
                )
                log_iteration_started(
                    LOGGER,
                    session_id=session_id,
                    iteration=iteration + 1,
                    current_score=float(results[-1].get("score", 0.0)) if results else 0.0,
                    feedback_count=0,
                    component=self.__class__.__name__,
                )
                result = self.run_once(session_id=f"{session_id}-{iteration + 1}")
                results.append(result)
                score = float(result.get("score", 0.0))
                valid = bool(result.get("valid", False))
                selected_task = self._current_plan_task()
                self._write_status(
                    "iteration_completed",
                    session_id=session_id,
                    iteration=iteration + 1,
                    selected_task=selected_task.label if selected_task else "",
                    valid=valid,
                    score=score,
                    artifact=result.get("artifact", {}),
                )
                log_iteration_complete(
                    LOGGER,
                    session_id=session_id,
                    iteration=iteration + 1,
                    score=score,
                    score_delta=score - (float(results[-2].get("score", 0.0)) if len(results) > 1 else 0.0),
                    execution_time_ms=(time.time() - iteration_started) * 1000,
                    component=self.__class__.__name__,
                )
                if valid and score >= self.daemon_config.target_score:
                    break
                if self.daemon_config.interval_seconds > 0 and iteration < self.daemon_config.max_iterations - 1:
                    time.sleep(self.daemon_config.interval_seconds)
        except Exception as exc:
            log_error(LOGGER, "logic_port_daemon_failed", error_msg=str(exc), session_id=session_id, component=self.__class__.__name__)
            results.append(
                {
                    "artifact": {
                        "summary": "Daemon failed before producing valid candidate changes.",
                        "target_task": self._current_plan_task().label if self._current_plan_task() else "",
                        "impact": "",
                        "tasks": [],
                        "has_patch": False,
                        "has_audit_diff": False,
                        "uses_worktree_transport": self.daemon_config.proposal_transport_mode() == "worktree",
                        "files": [],
                        "applied": False,
                        "dry_run": self.daemon_config.dry_run,
                        "validation_passed": False,
                        "validation_results": [],
                        "errors": [str(exc)],
                        "changed_files": [],
                        "failure_kind": "daemon_exception",
                    },
                    "score": 0.0,
                    "iterations": len(results),
                    "valid": False,
                    "metadata": {
                        "model_name": self.daemon_config.model_name,
                        "provider": self._resolved_provider() or "auto",
                    },
                }
            )
        finally:
            final_score = float(results[-1].get("score", 0.0)) if results else 0.0
            final_valid = bool(results[-1].get("valid", False)) if results else False
            log_session_complete(
                LOGGER,
                session_id=session_id,
                domain="logic-port",
                iterations=len(results),
                final_score=final_score,
                valid=final_valid,
                execution_time_ms=(time.time() - started) * 1000,
                component=self.__class__.__name__,
            )
            self._update_task_board(results)
            self._append_accepted_work_log(results)
            self._auto_commit_accepted_results(results)
            self._write_status(
                "session_completed",
                session_id=session_id,
                valid=final_valid,
                score=final_score,
                result_count=len(results),
                artifact=results[-1].get("artifact", {}) if results else {},
            )
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1.0)
        return results

    def run_supervised(self, *, cycles: int = 0) -> List[Dict[str, Any]]:
        """Run daemon cycles without user input.

        Args:
            cycles: Number of cycles to run. ``0`` means run until externally
                stopped. Each cycle runs :meth:`run_daemon`.

        Returns:
            Aggregated results for bounded runs. For unbounded runs this only
            returns when interrupted or when ``max_failure_cycles`` is reached.
        """

        all_results: List[Dict[str, Any]] = []
        failure_cycles = 0
        completed_cycles = 0

        while cycles <= 0 or completed_cycles < cycles:
            completed_cycles += 1
            if self.daemon_config.auto_commit_startup_dirty:
                self._auto_commit_startup_dirty_scope()
            self._block_current_task_if_stale_failed()
            terminal_result = self._no_eligible_task_result()
            if terminal_result is not None:
                added_tasks = self._replenish_plan_from_code_state()
                if added_tasks:
                    self._write_status(
                        "plan_replenished",
                        cycle=completed_cycles,
                        added_tasks=added_tasks,
                        selected_task=self._current_plan_task().label if self._current_plan_task() else "",
                    )
                    self._write_progress_summary(
                        completed_cycles=completed_cycles,
                        consecutive_failure_cycles=failure_cycles,
                        active_state="plan_replenished",
                    )
                    completed_cycles -= 1
                    continue

                all_results.append(terminal_result)
                self._update_task_board([terminal_result])
                self._write_status(
                    "no_eligible_tasks",
                    cycle=completed_cycles,
                    artifact=terminal_result.get("artifact", {}),
                )
                self._write_progress_summary(
                    cycle_results=[terminal_result],
                    completed_cycles=completed_cycles,
                    consecutive_failure_cycles=failure_cycles,
                    active_state="no_eligible_tasks",
                )
                self._append_result_log([terminal_result])
                break

            selected_task = self._current_plan_task()
            self._write_status("cycle_started", cycle=completed_cycles, selected_task=selected_task.label if selected_task else "")
            self._write_progress_summary(
                completed_cycles=completed_cycles,
                consecutive_failure_cycles=failure_cycles,
                active_state="cycle_started",
            )
            cycle_results = self.run_daemon()
            all_results.extend(cycle_results)
            self._write_progress_summary(cycle_results=cycle_results, completed_cycles=completed_cycles, consecutive_failure_cycles=failure_cycles)
            self._append_result_log(cycle_results)
            cycle_valid = bool(cycle_results and cycle_results[-1].get("valid"))
            self._write_status(
                "cycle_completed",
                cycle=completed_cycles,
                valid=cycle_valid,
                consecutive_failure_cycles=failure_cycles,
                artifact=cycle_results[-1].get("artifact", {}) if cycle_results else {},
            )
            if cycle_valid:
                failure_cycles = 0
            else:
                failure_cycles += 1
                self._write_progress_summary(cycle_results=cycle_results, completed_cycles=completed_cycles, consecutive_failure_cycles=failure_cycles)
                self._write_status(
                    "cycle_failed",
                    cycle=completed_cycles,
                    consecutive_failure_cycles=failure_cycles,
                    artifact=cycle_results[-1].get("artifact", {}) if cycle_results else {},
                )
                if self.daemon_config.max_failure_cycles and failure_cycles >= self.daemon_config.max_failure_cycles:
                    break

            if cycles > 0 and completed_cycles >= cycles:
                break

            if self.daemon_config.retry_interval_seconds > 0:
                time.sleep(self.daemon_config.retry_interval_seconds)

        return all_results

    def _no_eligible_task_result(self) -> Optional[Dict[str, Any]]:
        tasks = self._current_plan_tasks()
        if not tasks or self._select_next_plan_task(tasks) is not None:
            return None

        counts: Dict[str, int] = {}
        for task in tasks:
            counts[task.status] = counts.get(task.status, 0) + 1
        summary = "No eligible TypeScript port-plan tasks remain."
        if counts.get("blocked"):
            summary += " Blocked tasks require plan updates or a deliberate unblock before more autonomous work can run."

        return {
            "artifact": {
                "summary": summary,
                "target_task": "",
                "impact": "The daemon stopped before calling the LLM because every parsed port-plan task is complete or blocked.",
                "tasks": [],
                "has_patch": False,
                "has_audit_diff": False,
                "uses_worktree_transport": self.daemon_config.proposal_transport_mode() == "worktree",
                "files": [],
                "applied": False,
                "dry_run": self.daemon_config.dry_run,
                "validation_passed": False,
                "validation_results": [],
                "errors": [],
                "changed_files": [],
                "failure_kind": "no_eligible_tasks",
                "plan_status_counts": counts,
            },
            "score": 1.0,
            "iterations": 0,
            "valid": True,
            "metadata": {
                "model_name": self.daemon_config.model_name,
                "provider": self._resolved_provider() or "auto",
                "terminal_reason": "no_eligible_tasks",
            },
        }

    def _replenish_plan_from_code_state(self) -> List[str]:
        if (
            self.daemon_config.dry_run
            or not self.daemon_config.replenish_plan_when_empty
            or self.daemon_config.task_board_doc is None
        ):
            return []
        limit = max(0, int(self.daemon_config.plan_replenishment_limit))
        if limit <= 0:
            return []

        plan_path = self.daemon_config.resolve(self.daemon_config.task_board_doc)
        if not plan_path.exists():
            return []

        original = plan_path.read_text(encoding="utf-8")
        task_text = _strip_daemon_task_board(original)
        existing_titles = {task.title.lower() for task in extract_plan_tasks(task_text)}
        candidates = self._discover_plan_replenishment_tasks(existing_titles, limit=limit)
        if len(candidates) < limit:
            combined_titles = set(existing_titles)
            combined_titles.update(title.lower() for title in candidates)
            candidates.extend(self._discover_goal_review_replenishment_tasks(combined_titles, limit=limit - len(candidates)))
        if not candidates:
            return []

        section_heading = "## Daemon-Discovered Implementation Gaps"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = [
            "",
            section_heading,
            "",
            f"Last replenished: {timestamp}",
            "",
            "These tasks were added automatically after the daemon found no eligible unchecked port-plan items. They are derived from the current Python logic inventory, TypeScript/WASM implementation state, accepted-work evidence, and the original browser-native parity goal.",
            "",
        ]
        lines.extend(f"- [ ] {title}" for title in candidates)

        if section_heading in task_text:
            task_text = task_text.rstrip() + "\n" + "\n".join(f"- [ ] {title}" for title in candidates) + "\n"
        else:
            task_text = task_text.rstrip() + "\n\n" + "\n".join(lines) + "\n"

        tasks_after = extract_plan_tasks(task_text)
        current_target = self._select_next_plan_task(tasks_after)
        board = self._render_task_board(tasks_after, current_target=current_target, latest_target=current_target, results=[])
        plan_path.write_text(task_text.rstrip() + "\n\n" + board + "\n", encoding="utf-8")
        return candidates

    def _discover_plan_replenishment_tasks(self, existing_titles: set[str], *, limit: int) -> List[str]:
        candidates: List[str] = []
        ts_root = self.daemon_config.resolve(self.daemon_config.typescript_logic_dir)
        py_root = self.daemon_config.resolve(self.daemon_config.python_logic_dir)
        ts_files = [path for path in ts_root.rglob("*.ts") if path.is_file()] if ts_root.exists() else []
        ts_stems = {path.stem.lower() for path in ts_files}

        if py_root.exists():
            for path in sorted(py_root.rglob("*.py")):
                if path.name == "__init__.py" or path.name.startswith("test_"):
                    continue
                relative = path.relative_to(py_root).as_posix()
                stem = path.stem.lower()
                if stem in ts_stems:
                    continue
                title = (
                    f"Port remaining Python logic module `logic/{relative}` to browser-native TypeScript/WASM, "
                    "including focused validation tests and no server or Python runtime dependency."
                )
                if title.lower() not in existing_titles and title not in candidates:
                    candidates.append(title)
                if len(candidates) >= limit:
                    return candidates

        gap_patterns = (
            ("nlpUnavailable", "Replace remaining `nlpUnavailable` capability paths with browser-native NLP parity or explicit local model artifact loading."),
            ("mlUnavailable", "Replace remaining `mlUnavailable` capability paths with browser-native ML confidence parity or explicit local model artifact loading."),
            ("not implemented", "Resolve remaining TypeScript logic `not implemented` markers with browser-native implementations or documented parity exceptions."),
            ("unsupported", "Audit remaining TypeScript logic `unsupported` paths and convert feasible ones into browser-native TypeScript/WASM implementations."),
        )
        for pattern, title in gap_patterns:
            if title.lower() in existing_titles or title in candidates:
                continue
            for path in ts_files:
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if pattern in text:
                    candidates.append(title)
                    break
            if len(candidates) >= limit:
                return candidates

        return candidates[:limit]

    def _discover_goal_review_replenishment_tasks(self, existing_titles: set[str], *, limit: int) -> List[str]:
        if limit <= 0:
            return []

        evidence = self._collect_goal_review_evidence()
        templates = [
            (
                "Review the accepted TypeScript logic changes against the original browser-native TypeScript/WASM port goal, "
                "then add or implement any missing parity tasks for Python logic behavior that lacks accepted-work evidence."
            ),
            (
                "Add end-to-end browser-native validation proving the converted logic runs without Python, spaCy, "
                "or server-side calls, including deterministic coverage for ML and NLP capability surfaces."
            ),
            (
                "Audit Python ML and spaCy expectations against the TypeScript/WASM implementation and add focused parity "
                "tests or local-model artifact loading tasks for unsupported browser-native behavior."
            ),
            (
                "Refresh the TypeScript port plan with a parity matrix mapping Python logic modules, TypeScript/WASM files, "
                "validation evidence, accepted work, and remaining browser-native tasks."
            ),
            (
                "Compare TypeScript logic public exports against Python logic module public APIs and add missing browser-native "
                "compatibility adapters or parity tests."
            ),
        ]
        if evidence["accepted_rounds"] == 0:
            templates.insert(
                0,
                (
                    "Create accepted-work parity evidence for the current TypeScript/WASM logic port by linking completed "
                    "tasks to changed files, validation commands, and remaining Python logic gaps."
                ),
            )
        if evidence["python_files"] and evidence["ts_files"] and evidence["python_files"] > evidence["ts_files"]:
            templates.insert(
                0,
                (
                    f"Reconcile the Python logic inventory ({evidence['python_files']} files) with the TypeScript/WASM "
                    f"implementation ({evidence['ts_files']} files) and add browser-native port tasks for uncovered behavior."
                ),
            )

        candidates: List[str] = []
        for title in templates:
            if title.lower() in existing_titles or title in candidates:
                continue
            candidates.append(title)
            if len(candidates) >= limit:
                break
        return candidates

    def _collect_goal_review_evidence(self) -> Dict[str, int]:
        py_root = self.daemon_config.resolve(self.daemon_config.python_logic_dir)
        ts_root = self.daemon_config.resolve(self.daemon_config.typescript_logic_dir)
        python_files = 0
        ts_files = 0
        if py_root.exists():
            python_files = sum(
                1
                for path in py_root.rglob("*.py")
                if path.is_file() and path.name != "__init__.py" and not path.name.startswith("test_")
            )
        if ts_root.exists():
            ts_files = sum(1 for path in ts_root.rglob("*.ts") if path.is_file())

        accepted_rounds = 0
        if self.daemon_config.result_log_path is not None:
            rows = _read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path))
            accepted_rounds = sum(1 for result, _artifact in rows if result.get("valid"))
        if accepted_rounds == 0 and self.daemon_config.progress_path is not None:
            path = self.daemon_config.resolve(self.daemon_config.progress_path)
            if path.exists():
                try:
                    progress = json.loads(path.read_text(encoding="utf-8"))
                    accepted_rounds = int(progress.get("valid_rounds_total") or 0)
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    accepted_rounds = 0
        if accepted_rounds == 0 and self.daemon_config.accepted_work_log_path is not None:
            path = self.daemon_config.resolve(self.daemon_config.accepted_work_log_path)
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="ignore")
                accepted_rounds = len(re.findall(r"^##\s+", text, re.MULTILINE))

        return {
            "python_files": python_files,
            "ts_files": ts_files,
            "accepted_rounds": accepted_rounds,
        }

    def _block_current_task_if_stale_failed(self) -> bool:
        if self.daemon_config.dry_run or self.daemon_config.task_board_doc is None:
            return False
        if self.daemon_config.revisit_blocked_tasks:
            return False
        if (
            self.daemon_config.max_task_total_failure_rounds <= 0
            and self.daemon_config.max_task_failure_rounds <= 0
        ) or self.daemon_config.result_log_path is None:
            return False
        path = self.daemon_config.resolve(self.daemon_config.task_board_doc)
        if not path.exists():
            return False
        original = path.read_text(encoding="utf-8")
        task_text = _strip_daemon_task_board(original)
        tasks = extract_plan_tasks(task_text)
        current = self._select_next_plan_task(tasks)
        if current is None:
            return False
        rows = _read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path))
        if not self._task_failure_budget_exhausted(current, rows):
            return False
        task_text = _replace_checkbox_mark(task_text, current, "!")
        tasks_after = extract_plan_tasks(task_text)
        next_target = self._select_next_plan_task(tasks_after)
        board = self._render_task_board(tasks_after, current_target=next_target, latest_target=current, results=[])
        path.write_text(task_text.rstrip() + "\n\n" + board + "\n", encoding="utf-8")
        self._write_status(
            "task_blocked_before_cycle",
            blocked_task=current.label,
            selected_task=next_target.label if next_target else "",
        )
        return True

    def _append_result_log(self, results: List[Dict[str, Any]]) -> None:
        if self.daemon_config.result_log_path is None:
            return
        path = self.daemon_config.resolve(self.daemon_config.result_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "results": results}, default=str))
            handle.write("\n")

    def _write_progress_summary(
        self,
        *,
        cycle_results: Optional[List[Dict[str, Any]]] = None,
        completed_cycles: int = 0,
        consecutive_failure_cycles: int = 0,
        active_state: str = "",
    ) -> None:
        if self.daemon_config.progress_path is None:
            return

        rows: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        if self.daemon_config.result_log_path is not None:
            rows.extend(_read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path)))
        for result in cycle_results or []:
            artifact = result.get("artifact", {}) if isinstance(result, dict) else {}
            if isinstance(artifact, dict):
                rows.append((result, artifact))

        terminal_rows = [
            (result, artifact)
            for result, artifact in rows
            if artifact.get("failure_kind") == "no_eligible_tasks"
            or (isinstance(result.get("metadata"), dict) and result.get("metadata", {}).get("terminal_reason") == "no_eligible_tasks")
        ]
        work_rows = [(result, artifact) for result, artifact in rows if (result, artifact) not in terminal_rows]
        valid_rows = [(result, artifact) for result, artifact in work_rows if result.get("valid")]
        latest_result, latest_artifact = rows[-1] if rows else ({}, {})
        failure_kind_counts: Dict[str, int] = {}
        recent_failures = []
        for result, artifact in work_rows:
            if result.get("valid"):
                continue
            kind = _classify_failure_kind(artifact)
            failure_kind_counts[kind] = failure_kind_counts.get(kind, 0) + 1
        for result, artifact in work_rows[-20:]:
            if result.get("valid"):
                continue
            recent_failures.append(
                {
                    "target_task": artifact.get("target_task", ""),
                    "summary": _compact_message(artifact.get("summary", ""), limit=200),
                    "failure_kind": _classify_failure_kind(artifact),
                    "errors": [_compact_message(error, limit=240) for error in artifact.get("errors", [])[:3]]
                    if isinstance(artifact.get("errors", []), list)
                    else [_compact_message(artifact.get("errors", ""), limit=240)],
                }
            )
        current_task = self._current_plan_task()
        tasks = self._current_plan_tasks()
        current_task_counts = _current_task_failure_counts(rows, current_task.label) if current_task else {}
        typescript_quality_failures = _typescript_quality_failure_counts(work_rows)
        rollback_quality_failures = _rollback_quality_failure_counts(work_rows)
        blocked_backlog = self._blocked_task_backlog(tasks, rows)
        status_counts: Dict[str, int] = {}
        for task in tasks:
            status_counts[task.status] = status_counts.get(task.status, 0) + 1

        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema": "ipfs_datasets_py.logic_port_daemon.progress",
            "schema_version": 1,
            "pid": os.getpid(),
            "timestamp": now,
            "updated_at": now,
            "active_state": active_state,
            "completed_cycles_this_process": completed_cycles,
            "consecutive_failure_cycles": consecutive_failure_cycles,
            "rounds_total": len(work_rows),
            "terminal_events_total": len(terminal_rows),
            "valid_rounds_total": len(valid_rows),
            "invalid_rounds_total": len(work_rows) - len(valid_rows),
            "stagnant_rounds_since_valid": _rounds_since_last_valid(work_rows),
            "acceptance_rate": (len(valid_rows) / len(work_rows)) if work_rows else 0.0,
            "current_task": current_task.label if current_task else "",
            "current_task_failure_counts": current_task_counts,
            "blocked_backlog": blocked_backlog,
            "blocked_task_strategy": self.daemon_config.blocked_task_strategy,
            "slice_mode": self.daemon_config.slice_mode,
            "proposal_transport": self.daemon_config.proposal_transport_mode(),
            "worktree_edit_timeout_seconds": self.daemon_config.worktree_edit_timeout_seconds,
            "worktree_stale_after_seconds": self.daemon_config.worktree_stale_after_seconds,
            "worktree_codex_sandbox": self.daemon_config.worktree_codex_sandbox,
            "worktree_root": str(self.daemon_config.resolved_worktree_root()),
            "worktree_repair_attempts": self.daemon_config.worktree_repair_attempts,
            "auto_commit": self.daemon_config.auto_commit,
            "auto_commit_branch": self.daemon_config.auto_commit_branch,
            "auto_commit_startup_dirty": self.daemon_config.auto_commit_startup_dirty,
            "plan_status_counts": status_counts,
            "failure_kind_counts": failure_kind_counts,
            "typescript_quality_failures": typescript_quality_failures,
            "rollback_quality_failures": rollback_quality_failures,
            "latest_round": {
                "valid": bool(latest_result.get("valid")),
                "score": latest_result.get("score"),
                "target_task": latest_artifact.get("target_task", ""),
                "summary": _compact_message(latest_artifact.get("summary", ""), limit=400),
                "impact": _compact_message(latest_artifact.get("impact", ""), limit=500),
                "failure_kind": _classify_failure_kind(latest_artifact) if latest_artifact else "",
                "changed_files": latest_artifact.get("changed_files", []),
                "errors": [_compact_message(error, limit=360) for error in latest_artifact.get("errors", [])[:5]]
                if isinstance(latest_artifact.get("errors", []), list)
                else [_compact_message(latest_artifact.get("errors", ""), limit=360)],
            },
            "recent_failures": recent_failures[-5:],
            "recent_valid_rounds": [
                {
                    "target_task": artifact.get("target_task", ""),
                    "summary": _compact_message(artifact.get("summary", ""), limit=240),
                    "changed_files": artifact.get("changed_files", []),
                }
                for _, artifact in valid_rows[-5:]
            ],
        }

        path = self.daemon_config.resolve(self.daemon_config.progress_path)
        _shared_atomic_write_json(path, payload)

    def _start_status_heartbeat(self) -> Tuple[threading.Event, Optional[threading.Thread]]:
        stop = threading.Event()
        interval = float(self.daemon_config.heartbeat_interval_seconds)
        if self.daemon_config.status_path is None or interval <= 0:
            return stop, None

        def beat() -> None:
            while not stop.wait(interval):
                with self._status_lock:
                    base = dict(self._last_status_payload)
                if not base:
                    continue
                now = datetime.now(timezone.utc).isoformat()
                payload = _shared_build_heartbeat_status_payload(
                    base,
                    now=now,
                    timestamp_key="timestamp",
                    active_state_from_key="state",
                    active_started_from_key="state_started_at",
                    heartbeat_interval_seconds=interval,
                )
                self._write_status_payload(payload)
                self._write_progress_summary(active_state=base.get("state", "heartbeat"))

        thread = threading.Thread(target=beat, name="logic-port-daemon-heartbeat", daemon=True)
        thread.start()
        return stop, thread

    def _write_status_payload(self, payload: Dict[str, Any]) -> None:
        if self.daemon_config.status_path is None:
            return
        path = self.daemon_config.resolve(self.daemon_config.status_path)
        _shared_atomic_write_json(path, payload)

    def _write_status(self, state: str, **details: Any) -> None:
        if self.daemon_config.status_path is None:
            return
        artifact = details.get("artifact")
        if isinstance(artifact, dict):
            details["artifact"] = _shared_compact_status_artifact(
                artifact,
                classify_failure_kind=_classify_failure_kind,
            )
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema": "ipfs_datasets_py.logic_port_daemon.status",
            "schema_version": 1,
            "pid": os.getpid(),
            "timestamp": now,
            "updated_at": now,
            "heartbeat_at": now,
            "state": state,
            "slice_mode": self.daemon_config.slice_mode,
            "model_name": self.daemon_config.model_name,
            "provider": self._resolved_provider() or "auto",
            "proposal_transport": self.daemon_config.proposal_transport_mode(),
            "worktree_edit_timeout_seconds": self.daemon_config.worktree_edit_timeout_seconds,
            "worktree_stale_after_seconds": self.daemon_config.worktree_stale_after_seconds,
            "worktree_codex_sandbox": self.daemon_config.worktree_codex_sandbox,
            "worktree_root": str(self.daemon_config.resolved_worktree_root()),
            "worktree_repair_attempts": self.daemon_config.worktree_repair_attempts,
            "auto_commit": self.daemon_config.auto_commit,
            "auto_commit_branch": self.daemon_config.auto_commit_branch,
            "auto_commit_startup_dirty": self.daemon_config.auto_commit_startup_dirty,
            **details,
        }
        if state != "heartbeat":
            with self._status_lock:
                previous = self._last_status_payload
                payload["state_started_at"] = _shared_status_started_at(
                    previous,
                    state=state,
                    now=payload["timestamp"],
                )
                self._last_status_payload = dict(payload)
        self._write_status_payload(payload)

    def _append_accepted_work_log(self, results: List[Dict[str, Any]]) -> None:
        if self.daemon_config.accepted_work_log_path is None or not results:
            return
        latest = results[-1]
        if not latest.get("valid"):
            return
        artifact = latest.get("artifact", {}) if isinstance(latest.get("artifact"), dict) else {}
        changed_files = [str(path) for path in artifact.get("changed_files", []) if str(path)]
        if not changed_files:
            return

        artifact_paths = self._write_accepted_work_artifacts(artifact, changed_files)
        path = self.daemon_config.resolve(self.daemon_config.accepted_work_log_path)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        _shared_append_accepted_work_markdown_log(
            path,
            _shared_accepted_work_markdown_entry(
                timestamp=timestamp,
                target_task=str(artifact.get("target_task") or "unknown"),
                summary=str(artifact.get("summary") or "No summary"),
                impact=str(artifact.get("impact") or ""),
                changed_files=changed_files,
                evidence_paths=artifact_paths,
                validation_results=artifact.get("validation_results", []),
            ),
            title="Logic Port Daemon Accepted Work",
            description="This file is append-only daemon evidence for validated work that changed files used by the TypeScript port.",
        )

    def _auto_commit_accepted_results(self, results: List[Dict[str, Any]]) -> None:
        if not results:
            return
        latest = results[-1]
        if not latest.get("valid"):
            return
        artifact = latest.get("artifact", {}) if isinstance(latest.get("artifact"), dict) else {}
        changed_files = [str(path) for path in artifact.get("changed_files", []) if str(path)]
        commit_paths = [*changed_files]
        if self.daemon_config.task_board_doc is not None:
            commit_paths.append(self._repo_relative_pathspec(self.daemon_config.task_board_doc))
        if self.daemon_config.accepted_work_log_path is not None:
            commit_paths.append(self._repo_relative_pathspec(self.daemon_config.accepted_work_log_path))
        result = self._auto_commit_paths(
            commit_paths,
            reason="validated logic-port daemon round",
            target_task=str(artifact.get("target_task") or ""),
            summary=str(artifact.get("summary") or ""),
        )
        if result.get("attempted"):
            artifact["auto_commit"] = result

    def _auto_commit_startup_dirty_scope(self) -> None:
        paths = [
            self._repo_relative_pathspec(self.daemon_config.typescript_logic_dir),
        ]
        if self.daemon_config.task_board_doc is not None:
            paths.append(self._repo_relative_pathspec(self.daemon_config.task_board_doc))
        if self.daemon_config.accepted_work_log_path is not None:
            paths.append(self._repo_relative_pathspec(self.daemon_config.accepted_work_log_path))
        target_task = self._current_plan_task().label if self._current_plan_task() else ""
        summary = ""
        if self.daemon_config.progress_path is not None:
            try:
                progress = json.loads(self.daemon_config.resolve(self.daemon_config.progress_path).read_text(encoding="utf-8"))
            except Exception:
                progress = {}
            latest_round = progress.get("latest_round", {}) if isinstance(progress, dict) else {}
            if isinstance(latest_round, dict) and latest_round.get("valid"):
                target_task = str(latest_round.get("target_task") or target_task)
                summary = str(latest_round.get("summary") or "")
        self._auto_commit_paths(
            paths,
            reason="startup dirty daemon scope",
            target_task=target_task,
            summary=summary,
        )

    def _repo_relative_pathspec(self, path: Path) -> str:
        return _shared_repo_relative_pathspec(path, repo_root=self.daemon_config.repo_root)

    def _auto_commit_config(self) -> AutoCommitConfig:
        logic_dir = self._repo_relative_pathspec(self.daemon_config.typescript_logic_dir).rstrip("/")
        task_board = self._repo_relative_pathspec(self.daemon_config.task_board_doc) if self.daemon_config.task_board_doc else ""
        accepted_log = (
            self._repo_relative_pathspec(self.daemon_config.accepted_work_log_path)
            if self.daemon_config.accepted_work_log_path
            else ""
        )
        return AutoCommitConfig(
            repo_root=self.daemon_config.repo_root,
            enabled=self.daemon_config.auto_commit,
            dry_run=self.daemon_config.dry_run,
            required_branch=self.daemon_config.auto_commit_branch,
            allowed_prefixes=tuple(path for path in (*ALLOWED_WRITE_PREFIXES, logic_dir + "/") if path),
            allowed_exact_paths=tuple(path for path in (logic_dir, task_board, accepted_log) if path),
            command_timeout_seconds=self.daemon_config.command_timeout_seconds,
            subject_prefix="chore(logic-port):",
            user_name="Logic Port Daemon",
            user_email="logic-port-daemon@local",
        )

    def _auto_commit_paths(
        self,
        paths: Sequence[str],
        *,
        reason: str,
        target_task: str = "",
        summary: str = "",
    ) -> Dict[str, Any]:
        return _shared_auto_commit_paths(
            self._auto_commit_config(),
            paths,
            reason=reason,
            target_task=target_task,
            summary=summary,
            run_command_fn=run_command,
            write_status_fn=self._write_status,
        )

    def _safe_auto_commit_pathspecs(self, paths: Sequence[str]) -> List[str]:
        config = self._auto_commit_config()
        return _shared_safe_auto_commit_pathspecs(
            paths,
            allowed_prefixes=config.allowed_prefixes,
            allowed_exact_paths=config.allowed_exact_paths,
        )

    def _auto_commit_subject(self, *, target_task: str, summary: str, reason: str) -> str:
        return _shared_build_auto_commit_subject(
            target_task=target_task,
            summary=summary,
            reason=reason,
            subject_prefix="chore(logic-port):",
        )

    def _write_accepted_work_artifacts(self, artifact: Dict[str, Any], changed_files: List[str]) -> List[str]:
        if self.daemon_config.accepted_work_artifact_dir is None:
            return []
        return _shared_write_accepted_work_evidence_artifacts(
            root=self.daemon_config.resolve(self.daemon_config.accepted_work_artifact_dir),
            repo_root=self.daemon_config.repo_root,
            artifact=artifact,
            changed_files=changed_files,
            run_command_fn=run_command,
        )

    def _update_task_board(self, results: List[Dict[str, Any]]) -> None:
        if self.daemon_config.dry_run or not self.daemon_config.update_task_board or self.daemon_config.task_board_doc is None:
            return

        path = self.daemon_config.resolve(self.daemon_config.task_board_doc)
        if not path.exists():
            return

        original = path.read_text(encoding="utf-8")
        task_text = _strip_daemon_task_board(original)
        tasks_before = extract_plan_tasks(task_text)
        if not tasks_before:
            return

        latest = results[-1] if results else {}
        latest_valid = bool(latest.get("valid"))
        latest_target = self._task_from_latest_result(tasks_before, latest) or self._select_next_plan_task(tasks_before)
        if latest_valid and latest_target is not None:
            task_text = _replace_checkbox_mark(task_text, latest_target, "x")
        elif latest_target is not None and self._should_block_task(latest_target, latest):
            task_text = _replace_checkbox_mark(task_text, latest_target, "!")
        elif latest_target is not None and _task_is_explicit_failure(latest_target):
            task_text = _replace_checkbox_mark(task_text, latest_target, "!")

        tasks_after = extract_plan_tasks(task_text)
        current_target = self._select_next_plan_task(tasks_after)
        board = self._render_task_board(tasks_after, current_target=current_target, latest_target=latest_target, results=results)
        updated = task_text.rstrip() + "\n\n" + board + "\n"
        path.write_text(updated, encoding="utf-8")

    def _task_from_latest_result(self, tasks: Sequence[PlanTask], latest: Dict[str, Any]) -> Optional[PlanTask]:
        return _shared_plan_task_from_latest_result(tasks, latest)

    def _should_block_task(self, task: PlanTask, latest: Dict[str, Any]) -> bool:
        if self.daemon_config.max_task_failure_rounds <= 0 and self.daemon_config.max_task_total_failure_rounds <= 0:
            return False
        artifact = latest.get("artifact", {}) if isinstance(latest.get("artifact"), dict) else {}
        if self.daemon_config.result_log_path is None:
            return False
        rows = _read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path))
        # The current result is appended after the board update, so include it.
        rows = [*rows, (latest, artifact)]
        failure_kind = _classify_failure_kind(artifact)
        same_kind_blocked = (
            self.daemon_config.max_task_failure_rounds > 0
            and _recent_failure_count(rows, task.label, failure_kind) >= self.daemon_config.max_task_failure_rounds
        )
        total_blocked = (
            self.daemon_config.max_task_total_failure_rounds > 0
            and _recent_total_failure_count(rows, task.label) >= self.daemon_config.max_task_total_failure_rounds
        )
        return same_kind_blocked or total_blocked

    def _blocked_task_backlog(
        self,
        tasks: Sequence[PlanTask],
        rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        limit = max(0, int(self.daemon_config.blocked_backlog_limit))
        return _shared_build_blocked_task_backlog(
            tasks,
            rows,
            failure_summary_fn=lambda history_rows, task_label: _task_failure_summary(history_rows, task_label),
            failure_budget_exhausted_fn=self._task_failure_budget_exhausted,
            limit=limit,
        )

    def _blocked_task_backlog_markdown(
        self,
        tasks: Sequence[PlanTask],
        rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]],
    ) -> str:
        return _shared_blocked_task_backlog_markdown(self._blocked_task_backlog(tasks, rows))

    def _select_next_plan_task(self, tasks: List[PlanTask]) -> Optional[PlanTask]:
        return _shared_select_next_plan_task(
            tasks,
            revisit_blocked=self.daemon_config.revisit_blocked_tasks,
            blocked_selector=lambda plan_tasks: self._select_blocked_plan_task(plan_tasks),
        )

    def _select_blocked_plan_task(self, tasks: Sequence[PlanTask]) -> Optional[PlanTask]:
        rows: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        if self.daemon_config.result_log_path is not None:
            rows = _read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path))
        return _shared_select_blocked_plan_task(
            tasks,
            rows,
            strategy=self.daemon_config.blocked_task_strategy,
            dependency_reason_fn=self._blocked_task_dependency_reason,
            failure_budget_exhausted_fn=self._task_failure_budget_exhausted,
            recent_total_failure_count_fn=_recent_total_failure_count,
            last_task_attempt_index_fn=_last_task_attempt_index,
        )

    def _task_failure_budget_exhausted(
        self,
        task: PlanTask,
        rows: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]],
    ) -> bool:
        if (
            self.daemon_config.max_task_typescript_quality_rounds > 0
            and int(
                _current_task_failure_counts(rows, task.label)
                .get("by_kind_since_success", {})
                .get("typescript_quality", 0)
            )
            >= self.daemon_config.max_task_typescript_quality_rounds
        ):
            return True
        if (
            self.daemon_config.max_task_total_failure_rounds > 0
            and _recent_total_failure_count(rows, task.label) >= self.daemon_config.max_task_total_failure_rounds
        ):
            return True
        if self.daemon_config.max_task_failure_rounds <= 0:
            return False
        counts = _current_task_failure_counts(rows, task.label)
        by_kind = counts.get("by_kind_since_success", {}) if isinstance(counts, dict) else {}
        if any(int(count or 0) >= self.daemon_config.max_task_failure_rounds for count in by_kind.values()):
            return True
        return _recent_rollback_quality_failure_count(rows, task.label) >= self.daemon_config.max_task_failure_rounds

    def _blocked_task_dependency_reason(self, task: PlanTask, tasks: Sequence[PlanTask]) -> str:
        title = task.title.lower()
        is_capability_cleanup = (
            "remove" in title
            and ("capability flag" in title or "unavailable" in title)
            and ("nlpunavailable" in title or "mlunavailable" in title)
        )
        if not is_capability_cleanup:
            return ""

        unfinished_prerequisites = [
            item.label
            for item in tasks
            if item.task_id != task.task_id
            and item.status != "complete"
            and any(token in item.title.lower() for token in ("spacy", "browser-native nlp", "ml_confidence", "ml confidence"))
        ]
        if unfinished_prerequisites:
            return "ML/NLP prerequisite tasks are still unfinished."

        markers = self._runtime_capability_unavailable_markers()
        if markers:
            return "Runtime capability unavailable markers still exist in TypeScript logic."
        return ""

    def _runtime_capability_unavailable_markers(self) -> List[str]:
        ts_root = self.daemon_config.resolve(self.daemon_config.typescript_logic_dir)
        if not ts_root.exists():
            return []
        markers: List[str] = []
        for path in sorted(ts_root.rglob("*.ts")):
            if not path.is_file() or path.name.endswith(".test.ts"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for marker in ("nlpUnavailable", "mlUnavailable"):
                if marker in text:
                    try:
                        rel_path = path.relative_to(self.daemon_config.repo_root).as_posix()
                    except ValueError:
                        rel_path = path.as_posix()
                    markers.append(f"{rel_path}:{marker}")
        return markers

    def _render_task_board(
        self,
        tasks: List[PlanTask],
        *,
        current_target: Optional[PlanTask],
        latest_target: Optional[PlanTask],
        results: List[Dict[str, Any]],
    ) -> str:
        latest = results[-1] if results else {}
        latest_artifact = latest.get("artifact", {}) if isinstance(latest.get("artifact"), dict) else {}
        latest_valid = bool(latest.get("valid"))
        latest_summary = str(latest_artifact.get("summary") or "No summary")
        latest_impact = str(latest_artifact.get("impact") or "")
        latest_errors = latest_artifact.get("errors") or []
        latest_changed_files = [str(path) for path in latest_artifact.get("changed_files", []) if str(path)]
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        current_target_label = self._markdown_task_label(current_target) if current_target else "none"
        latest_target_label = self._markdown_task_label(latest_target) if latest_target else "none"
        rows: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        if self.daemon_config.result_log_path is not None:
            rows.extend(_read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path)))
        for result in results:
            artifact = result.get("artifact", {}) if isinstance(result, dict) else {}
            if isinstance(artifact, dict):
                rows.append((result, artifact))
        blocked_backlog = self._blocked_task_backlog(tasks, rows)

        lines = [
            "<!-- logic-port-daemon-task-board:start -->",
            "## Daemon Task Board",
            "",
            f"Last updated: {timestamp}",
            "",
            self._task_board_selection_policy(),
            "",
            f"Current target: `{current_target_label}`",
            "",
            "Legend: `[ ]` needed, `[~]` in progress, `[x]` complete, `[!]` blocked or failing.",
            "",
            "### Checklist",
            "",
        ]

        for task in tasks:
            marker = {"complete": "[x]", "in-progress": "[~]", "blocked": "[!]"}.get(task.status, "[ ]")
            note = task.status
            if latest_target and task.task_id == latest_target.task_id:
                if latest_valid:
                    marker = "[x]"
                    note = "validated by latest daemon round"
                elif latest:
                    marker = "[!]"
                    note = "latest daemon round failed validation or preflight"
                else:
                    marker = "[~]"
                    note = "selected for next daemon round"
            lines.append(f"- {marker} `{self._markdown_task_label(task)}` - {note}")

        lines.extend(
            [
                "",
                "### Latest Round",
                "",
                f"- Target: `{latest_target_label}`",
                f"- Result: `{'valid' if latest_valid else 'needs follow-up'}`",
                f"- Summary: {latest_summary}",
            ]
        )
        if latest_impact:
            lines.append(f"- Impact: {latest_impact}")
        if latest_changed_files:
            lines.append(f"- Accepted changed files: {', '.join(f'`{path}`' for path in latest_changed_files)}")
        if latest_errors:
            lines.append(f"- Errors: {'; '.join(str(error) for error in latest_errors[:3])}")
        if latest_artifact.get("failure_kind"):
            lines.append(f"- Failure kind: `{_classify_failure_kind(latest_artifact)}`")

        lines.extend(["", "### Blocked Backlog", ""])
        if blocked_backlog:
            for item in blocked_backlog:
                latest_failure = item.get("latest_failure", {}) if isinstance(item.get("latest_failure"), dict) else {}
                kinds = item.get("failure_kinds_since_success", {})
                task_label = str(item.get("task", "")).replace("`", "'")
                lines.append(f"- `{task_label}`")
                lines.append(f"  - Failures since success: `{item.get('total_failures_since_success', 0)}`")
                if item.get("failure_budget_exhausted"):
                    lines.append("  - Autonomous revisit: `skipped; task failure budget exhausted`")
                if kinds:
                    lines.append(f"  - Failure kinds: `{json.dumps(kinds, sort_keys=True)}`")
                if latest_failure.get("failure_kind"):
                    lines.append(f"  - Latest failure kind: `{latest_failure.get('failure_kind')}`")
                if latest_failure.get("errors"):
                    errors = latest_failure.get("errors", [])
                    lines.append(f"  - Latest errors: {'; '.join(str(error) for error in errors[:2])}")
        else:
            lines.append("- No blocked tasks in the current daemon backlog.")

        lines.extend(
            [
                "",
                "### Required Daemon Behavior",
                "",
                "- Work only on the current port-plan target unless the task is already complete in code and tests.",
                "- For implementation tasks, accepted work must change runtime TypeScript under `src/lib/logic/`; fixture-only work is reserved for fixture/capture/documentation tasks.",
                "- If a round fails, keep the task marked as needing follow-up and use the validation error as the next-cycle constraint.",
                "- Mark a task complete only after TypeScript validation and logic-port tests pass for the accepted change.",
                "- Keep browser runtime changes TypeScript/WASM-native with no server or Python service dependency.",
                "<!-- logic-port-daemon-task-board:end -->",
            ]
        )
        return "\n".join(lines)

    def _task_board_selection_policy(self) -> str:
        if self.daemon_config.revisit_blocked_tasks:
            return (
                "Selection policy: choose the first needed or in-progress port-plan checkbox; if none remain, "
                f"revisit blocked checkboxes with `{self.daemon_config.blocked_task_strategy}` strategy because blocked-task revisit mode is enabled."
            )
        return "Selection policy: choose the first port-plan checkbox that is not marked complete, keep the daemon scoped to that task, and update this board after every daemon round."

    def _markdown_task_label(self, task: Optional[PlanTask]) -> str:
        return _shared_markdown_task_label(task)

    def cleanup_stale_worktrees(self) -> Dict[str, Any]:
        """Remove daemon-created proposal worktrees left behind by crashes."""

        repo_root = self.daemon_config.repo_root
        return _shared_cleanup_stale_daemon_worktrees(
            repo_root=repo_root,
            worktree_root=self.daemon_config.resolved_worktree_root(),
            stale_after_seconds=max(1, int(self.daemon_config.worktree_stale_after_seconds)),
            owner_filename=".logic_port_worktree_owner.json",
            patterns=("cycle_*", "repair_*"),
            run_command_fn=run_command,
            owner_alive=lambda pid, _repo_root, worktree_path: _pid_looks_like_logic_port_owner(
                pid,
                repo_root=repo_root,
                worktree_path=worktree_path,
            ),
        )

    def _write_worktree_owner_file(self, path: Path, *, attempt: int) -> None:
        _shared_write_worktree_owner_file(
            path,
            schema="ipfs_datasets_py.logic_port_worktree_owner",
            repo_root=self.daemon_config.repo_root,
            attempt=attempt,
            extra={
                "worktree_edit_timeout_seconds": self.daemon_config.worktree_edit_timeout_seconds,
                "worktree_codex_sandbox": self.daemon_config.worktree_codex_sandbox,
            },
        )

    def _read_worktree_owner_file(self, path: Path) -> Dict[str, Any]:
        return _shared_read_json_object(path)

    def _read_worktree_metadata(self, path: Path) -> Dict[str, Any]:
        return _shared_read_json_object(path)

    def _repair_worktree_file_edits_after_validation(
        self,
        artifact: LogicPortArtifact,
        *,
        context: OptimizationContext,
    ) -> LogicPortArtifact:
        attempts = max(0, int(self.daemon_config.worktree_repair_attempts))
        if attempts <= 0 or not artifact.files:
            return LogicPortArtifact(raw_response=artifact.raw_response, proposal_transport="worktree")

        selected_task = self._current_plan_task()
        selected_label = artifact.target_task or (selected_task.label if selected_task else "unknown")
        repaired = LogicPortArtifact(raw_response=artifact.raw_response, proposal_transport="worktree")
        for attempt in range(1, attempts + 1):
            self._write_status(
                "repairing_failed_worktree_validation",
                attempt=attempt,
                attempts=attempts,
                selected_task=selected_label,
                failed_commands=[" ".join(result.command) for result in artifact.validation_results if not result.ok],
                timeout_seconds=self.daemon_config.worktree_edit_timeout_seconds,
                worktree_root=str(self.daemon_config.resolved_worktree_root()),
            )
            repaired = self._request_worktree_validation_repair_artifact(
                artifact=artifact,
                context=context,
                attempt=attempt,
                attempts=attempts,
            )
            if repaired.files and not repaired.errors:
                return repaired
        return repaired

    def _request_worktree_validation_repair_artifact(
        self,
        *,
        artifact: LogicPortArtifact,
        context: OptimizationContext,
        attempt: int,
        attempts: int,
    ) -> LogicPortArtifact:
        repo_root = self.daemon_config.repo_root
        worktree_root = self.daemon_config.resolved_worktree_root()
        cleanup_result = self.cleanup_stale_worktrees()
        worktree_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        worktree_path = worktree_root / f"repair_{attempt:02d}_{stamp}_{os.getpid()}"
        metadata_rel = ".logic_port_worktree_repair.json"
        owner_rel = ".logic_port_worktree_owner.json"
        raw_trace: Dict[str, Any] = {
            "transport": "worktree_validation_repair",
            "attempt": attempt,
            "attempts": attempts,
            "worktree_path": str(worktree_path),
            "metadata_path": metadata_rel,
            "owner_path": owner_rel,
            "cleanup_before_create": cleanup_result,
            "failed_validation_results": [result.compact(limit=12000) for result in artifact.validation_results if not result.ok],
            "candidate_summary": artifact.summary,
            "candidate_changed_files": _artifact_paths(artifact),
        }

        try:
            add_result = run_command(
                ("git", "worktree", "add", "--detach", str(worktree_path), "HEAD"),
                cwd=repo_root,
                timeout_seconds=60,
            )
            raw_trace["worktree_add"] = add_result.compact(limit=12000)
            if not add_result.ok:
                return LogicPortArtifact(
                    summary="Worktree validation repair failed before Codex edit.",
                    raw_response=json.dumps(raw_trace, indent=2, default=str),
                    errors=["git worktree add failed during validation repair: " + (add_result.stderr or add_result.stdout).strip()[:1000]],
                    failure_kind="worktree_repair_add",
                    proposal_transport="worktree",
                )

            self._write_worktree_owner_file(worktree_path / owner_rel, attempt=attempt)
            self._write_file_edits_to_root(worktree_path, artifact.files)
            self._format_file_edits_in_root(worktree_path, [str(edit.get("path", "")) for edit in artifact.files])
            base_patch = self._worktree_diff(worktree_path, raw_trace, label="base_candidate")

            prompt = self._build_worktree_validation_repair_prompt(
                artifact=artifact,
                context=context,
                metadata_rel=metadata_rel,
                attempt=attempt,
                attempts=attempts,
            )
            repair_result = run_command(
                (
                    self.daemon_config.codex_bin,
                    "exec",
                    "--skip-git-repo-check",
                    "--sandbox",
                    self.daemon_config.worktree_codex_sandbox,
                    "-m",
                    self.daemon_config.model_name,
                    "-C",
                    str(worktree_path),
                    "-",
                ),
                cwd=worktree_path,
                stdin=prompt,
                timeout_seconds=max(1, int(self.daemon_config.worktree_edit_timeout_seconds)),
            )
            raw_trace["codex_repair_exec"] = repair_result.compact(limit=20000)

            harvested = self._harvest_worktree_artifact(
                worktree_path,
                metadata_rel=metadata_rel,
                owner_rel=owner_rel,
                raw_trace=raw_trace,
                default_summary="Worktree validation repair proposal.",
                default_impact="Repaired the failed candidate in an isolated worktree before touching the main project again.",
            )
            if harvested.patch.strip() == base_patch.strip():
                harvested.errors.append("Worktree validation repair made no changes beyond the failed candidate.")
                harvested.failure_kind = harvested.failure_kind or "worktree_repair_no_change"
                harvested.files = []
                harvested.patch = ""
            if not repair_result.ok and not harvested.files:
                harvested.errors.append(
                    "Worktree validation repair command failed without producing usable changes: "
                    + (repair_result.stderr or repair_result.stdout).strip()[:1000]
                )
                harvested.failure_kind = harvested.failure_kind or "worktree_repair_codex_failed"
            harvested.proposal_transport = "worktree"
            harvested.target_task = artifact.target_task
            if not harvested.tasks:
                harvested.tasks = artifact.tasks
            return harvested
        finally:
            remove_result = run_command(
                ("git", "worktree", "remove", "--force", str(worktree_path)),
                cwd=repo_root,
                timeout_seconds=60,
            )
            if not remove_result.ok and worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
            run_command(
                ("git", "worktree", "prune", "--expire", "now"),
                cwd=repo_root,
                timeout_seconds=60,
            )

    def _build_worktree_validation_repair_prompt(
        self,
        *,
        artifact: LogicPortArtifact,
        context: OptimizationContext,
        metadata_rel: str,
        attempt: int,
        attempts: int,
    ) -> str:
        selected_task = self._current_plan_task()
        selected_task_text = artifact.target_task or (selected_task.label if selected_task else "[No parsed task found]")
        failed_results = [result.compact(limit=16000) for result in artifact.validation_results if not result.ok]
        attempted_files = [
            {
                "path": str(edit.get("path", "")),
                "content_prefix": str(edit.get("content", ""))[:12000],
            }
            for edit in artifact.files[:8]
        ]
        payload = {
            "transport": "worktree_validation_repair",
            "attempt": attempt,
            "attempts": attempts,
            "metadata_path": metadata_rel,
            "selected_task": selected_task_text,
            "allowed_edit_paths": self._worktree_diff_paths(),
            "failed_validation_results": failed_results,
            "candidate_summary": artifact.summary,
            "candidate_impact": artifact.impact,
            "candidate_tasks": artifact.tasks,
            "candidate_files": attempted_files,
            "required_metadata_schema": {
                "summary": "string",
                "impact": "string",
                "tasks": ["string"],
                "changed_files": ["string"],
                "validation_commands": [["string"]],
            },
        }
        prompt = f"""You are Codex running inside a throwaway Git worktree for the TypeScript/WASM logic-port daemon.
The previous direct-edit candidate is already applied in this isolated worktree, but the daemon's validation failed.

Repair the files directly in this worktree. Do not commit. Do not output or hand-author a patch.
The daemon will harvest Git's canonical diff and complete file contents after your repair, then rerun validation in the real project.

Hard constraints:
- Keep the repair scoped to the daemon-selected task: {selected_task_text}
- Preserve browser-native TypeScript/WASM behavior with no server calls, Python runtime bridge, filesystem/subprocess/RPC fallback, or Node-only browser-runtime dependency.
- Fix the exact TypeScript/test failures in failed_validation_results.
- Prefer minimal, compileable repairs over broad rewrites.
- Preserve public exports already present in touched modules unless the selected task explicitly removes them.
- Only edit paths listed in allowed_edit_paths.
- After editing, write strict JSON metadata to {metadata_rel}.

Repair payload:
{json.dumps(payload, indent=2, default=str)}
"""
        budget = max(4000, int(self.daemon_config.max_prompt_chars))
        if len(prompt) > budget:
            return prompt[:budget] + "\n\n[worktree validation repair prompt truncated]\n"
        return prompt

    def _build_worktree_edit_prompt(
        self,
        *,
        input_data: Any,
        context: OptimizationContext,
        metadata_rel: str,
        attempt: int,
        attempts: int,
        previous_feedback: str,
    ) -> str:
        selected_task = self._current_plan_task()
        selected_task_text = selected_task.label if selected_task else "[No parsed task found]"
        planning_context = self._build_prompt(input_data=input_data, context=context)
        payload = {
            "transport": "worktree_direct_edit",
            "attempt": attempt,
            "attempts": attempts,
            "metadata_path": metadata_rel,
            "selected_task": selected_task_text,
            "allowed_edit_paths": self._worktree_diff_paths(),
            "required_metadata_schema": {
                "summary": "string",
                "impact": "string",
                "tasks": ["string"],
                "changed_files": ["string"],
                "validation_commands": [["string"]],
            },
            "previous_rejection_feedback": previous_feedback,
        }
        header = f"""You are Codex running inside a throwaway Git worktree for the TypeScript/WASM logic-port daemon.
Edit files directly in this isolated worktree. Do not commit. Do not output or hand-author a patch.
The daemon will harvest Git's canonical diff and complete file contents after your edit, then validate them in the real project.

Task source:
- Use docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md as the controlling task ledger.
- Do not work from the deterministic legal-parser plans; that is a separate daemon.
- The daemon-selected task for this cycle is: {selected_task_text}

Hard constraints:
- Port Python ipfs_datasets_py logic behavior into browser-native TypeScript/WASM.
- Do not add server calls, Python runtime bridges, filesystem/subprocess/RPC fallbacks, or Node-only browser-runtime dependencies.
- Keep Python ML and spaCy parity in scope through deterministic TypeScript, browser-native model artifacts, or explicit fail-closed local adapters.
- Make one coherent implementation slice large enough to move parity, with focused Jest validation where relevant.
- Only edit paths listed in allowed_edit_paths.
- After editing, write strict JSON metadata to {metadata_rel}.

Worktree metadata payload:
{json.dumps(payload, indent=2, default=str)}

The planning context below may say to return JSON with `files` or `patch`; ignore that output-format instruction in worktree mode. Use direct file edits plus metadata JSON instead.

PLANNING CONTEXT:
"""
        prompt = header + planning_context
        budget = max(4000, int(self.daemon_config.max_prompt_chars))
        if len(prompt) > budget:
            return prompt[:budget] + "\n\n[worktree edit prompt truncated]\n"
        return prompt

    def _worktree_diff_paths(self) -> List[str]:
        paths = [
            self._repo_relative_path(self.daemon_config.typescript_logic_dir).rstrip("/"),
            "docs",
            "ipfs_datasets_py/docs/logic",
        ]
        ordered: List[str] = []
        seen = set()
        for path in paths:
            normalized = path.replace("\\", "/").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)
        return ordered

    def _repo_relative_path(self, path: Path) -> str:
        candidate = path if path.is_absolute() else self.daemon_config.repo_root / path
        try:
            return candidate.relative_to(self.daemon_config.repo_root).as_posix()
        except ValueError:
            return path.as_posix().replace("\\", "/")

    def _disallowed_worktree_paths(self, paths: Sequence[str], *, metadata_rel: str, owner_rel: str) -> List[str]:
        ignored = {metadata_rel, owner_rel}
        disallowed: List[str] = []
        for path in paths:
            normalized = path.replace("\\", "/")
            if normalized in ignored:
                continue
            if any(normalized.startswith(prefix) for prefix in ALLOWED_WRITE_PREFIXES):
                continue
            disallowed.append(normalized)
        return disallowed

    def _worktree_file_edits(self, worktree_path: Path, changed_files: Sequence[str]) -> List[Dict[str, str]]:
        edits: List[Dict[str, str]] = []
        seen = set()
        for path_text in changed_files:
            normalized = path_text.replace("\\", "/").strip()
            if not normalized or normalized in seen:
                continue
            if not any(normalized.startswith(prefix) for prefix in ALLOWED_WRITE_PREFIXES):
                continue
            path = worktree_path / normalized
            if not path.exists() or not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            edits.append({"path": normalized, "content": content})
            seen.add(normalized)
        return edits

    def _write_file_edits_to_root(self, root: Path, edits: Sequence[Dict[str, str]]) -> None:
        for edit in edits:
            raw_path = str(edit.get("path", ""))
            if not raw_path or raw_path.startswith("/") or ".." in Path(raw_path).parts:
                raise ValueError(f"Unsafe worktree repair edit path: {raw_path!r}")
            normalized = raw_path.replace("\\", "/")
            if not any(normalized.startswith(prefix) for prefix in ALLOWED_WRITE_PREFIXES):
                raise ValueError(f"Worktree repair edit path is outside daemon allowlist: {raw_path!r}")
            path = root / normalized
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(edit.get("content", "")), encoding="utf-8")

    def _format_file_edits_in_root(self, root: Path, paths: Sequence[str]) -> None:
        ts_paths = [
            path.replace("\\", "/")
            for path in paths
            if path and path.replace("\\", "/").endswith((".ts", ".tsx"))
        ]
        if not ts_paths:
            return
        run_command(
            ("npx", "prettier", "--write", *ts_paths),
            cwd=root,
            timeout_seconds=120,
        )

    def _worktree_diff(self, worktree_path: Path, raw_trace: Dict[str, Any], *, label: str) -> str:
        diff_paths = self._worktree_diff_paths()
        status_result = run_command(
            ("git", "status", "--porcelain", "--", *diff_paths),
            cwd=worktree_path,
            timeout_seconds=60,
        )
        raw_trace[f"{label}_status"] = status_result.compact(limit=12000)
        untracked_paths = _untracked_paths_from_git_status(status_result.stdout)
        raw_trace[f"{label}_untracked_paths"] = untracked_paths
        if untracked_paths:
            add_intent = run_command(
                ("git", "add", "-N", "--", *untracked_paths),
                cwd=worktree_path,
                timeout_seconds=60,
            )
            raw_trace[f"{label}_git_add_intent_to_add"] = add_intent.compact(limit=12000)
        diff_result = run_command(
            ("git", "diff", "--binary", "--", *diff_paths),
            cwd=worktree_path,
            timeout_seconds=60,
        )
        raw_trace[f"{label}_git_diff"] = diff_result.compact(limit=20000)
        return diff_result.stdout if diff_result.ok else ""

    def _harvest_worktree_artifact(
        self,
        worktree_path: Path,
        *,
        metadata_rel: str,
        owner_rel: str,
        raw_trace: Dict[str, Any],
        default_summary: str,
        default_impact: str,
    ) -> LogicPortArtifact:
        full_status = run_command(
            ("git", "status", "--porcelain"),
            cwd=worktree_path,
            timeout_seconds=60,
        )
        raw_trace["full_status"] = full_status.compact(limit=12000)
        disallowed_paths = self._disallowed_worktree_paths(
            _git_status_paths(full_status.stdout),
            metadata_rel=metadata_rel,
            owner_rel=owner_rel,
        )
        if disallowed_paths:
            raw_trace["disallowed_paths"] = disallowed_paths
            return LogicPortArtifact(
                summary="Worktree proposal edited paths outside the logic-port allowlist.",
                raw_response=json.dumps(raw_trace, indent=2, default=str),
                errors=["Worktree proposal edited disallowed paths: " + ", ".join(disallowed_paths[:12])],
                failure_kind="worktree_disallowed_paths",
                proposal_transport="worktree",
            )

        patch = self._worktree_diff(worktree_path, raw_trace, label="harvest")
        metadata = self._read_worktree_metadata(worktree_path / metadata_rel)
        raw_trace["metadata"] = metadata
        changed_files = _patch_changed_files(patch)
        if not changed_files:
            changed_files = [
                str(path)
                for path in metadata.get("changed_files", [])
                if isinstance(path, str) and path.strip()
            ] if isinstance(metadata.get("changed_files"), list) else []
        files = self._worktree_file_edits(worktree_path, changed_files)
        validation_commands = [
            [str(part) for part in command]
            for command in metadata.get("validation_commands", [])
            if isinstance(command, list) and all(isinstance(part, str) for part in command)
        ] if isinstance(metadata.get("validation_commands"), list) else []
        tasks = [
            str(item)
            for item in metadata.get("tasks", [])
            if isinstance(item, (str, int, float)) and str(item).strip()
        ] if isinstance(metadata.get("tasks"), list) else []
        errors: List[str] = []
        failure_kind = ""
        if not patch.strip() and not files:
            errors.append("worktree edit produced no allowed TypeScript port changes")
            failure_kind = "worktree_no_change"
        selected_task = self._current_plan_task()
        return LogicPortArtifact(
            summary=str(metadata.get("summary") or default_summary),
            impact=str(metadata.get("impact") or default_impact),
            patch=patch,
            files=files,
            tasks=tasks or ([selected_task.label] if selected_task else []),
            validation_commands=validation_commands,
            raw_response=json.dumps(raw_trace, indent=2, default=str),
            errors=errors,
            failure_kind=failure_kind,
            changed_files=changed_files,
            proposal_transport="worktree",
        )

    def _safe_edit_path(self, raw_path: str) -> Path:
        if not raw_path or raw_path.startswith("/") or ".." in Path(raw_path).parts:
            raise ValueError(f"Unsafe file edit path: {raw_path!r}")
        normalized = raw_path.replace("\\", "/")
        if not any(normalized.startswith(prefix) for prefix in ALLOWED_WRITE_PREFIXES):
            raise ValueError(f"File edit path is outside daemon allowlist: {raw_path!r}")
        return self.daemon_config.resolve(Path(normalized))

    def _dirty_touched_file_errors(self, paths: Sequence[str]) -> List[str]:
        normalized_paths = []
        seen = set()
        for path in paths:
            normalized = str(path or "").replace("\\", "/").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                normalized_paths.append(normalized)
        if not normalized_paths:
            return []
        status = run_command(
            ("git", "status", "--porcelain", "--", *normalized_paths),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=min(60, max(1, self.daemon_config.command_timeout_seconds)),
        )
        if not status.ok:
            return []
        dirty = _git_status_paths(status.stdout)
        if not dirty:
            return []
        return [
            "Rejected proposal because these touched files already have uncommitted changes in the main worktree: "
            + ", ".join(dirty[:20])
        ]

    def _apply_file_edits_with_validation(self, edits: List[Dict[str, str]]) -> Tuple[bool, List[CommandResult], List[str]]:
        originals: Dict[Path, Optional[str]] = {}
        touched: List[Path] = []
        applied = False
        dirty_errors = self._dirty_touched_file_errors([str(edit.get("path", "")) for edit in edits])
        if dirty_errors:
            self._auto_commit_paths(
                [str(edit.get("path", "")) for edit in edits],
                reason="dirty touched files before applying file replacements",
            )
            dirty_errors = self._dirty_touched_file_errors([str(edit.get("path", "")) for edit in edits])
        if dirty_errors:
            raise ValueError(dirty_errors[0])
        for edit in edits:
            path = self._safe_edit_path(edit["path"])
            if path not in originals:
                originals[path] = path.read_text(encoding="utf-8") if path.exists() else None
            touched.append(path)

        try:
            for edit in edits:
                path = self._safe_edit_path(edit["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(edit["content"], encoding="utf-8")
            self._format_file_edits(touched)
            validation_results = self._run_validation()
            changed_files = sorted(
                str(path.relative_to(self.daemon_config.repo_root))
                for path in originals
                if (path.read_text(encoding="utf-8") if path.exists() else None) != originals[path]
            )
            applied = all(result.ok for result in validation_results) and bool(changed_files)
            return applied, validation_results, changed_files
        finally:
            validation_results = locals().get("validation_results")
            if not applied and (not validation_results or not all(result.ok for result in validation_results)):
                for path, original in originals.items():
                    if original is None:
                        try:
                            path.unlink()
                        except FileNotFoundError:
                            pass
                    else:
                        path.write_text(original, encoding="utf-8")

    def _format_file_edits(self, paths: List[Path]) -> None:
        ts_paths = [str(path.relative_to(self.daemon_config.repo_root)) for path in paths if path.suffix in {".ts", ".tsx"}]
        if not ts_paths:
            return
        run_command(
            ("npx", "prettier", "--write", *ts_paths),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=120,
        )

    def _preflight_artifact(self, artifact: LogicPortArtifact, *, selected_task: Optional[PlanTask] = None) -> List[str]:
        paths = _artifact_paths(artifact)
        return _shared_preflight_proposal_payload(
            patch=artifact.patch,
            files=artifact.files,
            paths=paths,
            selected_task=selected_task,
            proposal_transport=artifact.proposal_transport,
            default_transport=self.daemon_config.proposal_transport_mode(),
            policy=replace(LOGIC_PORT_PREFLIGHT_POLICY, prefer_file_edits=self.daemon_config.prefer_file_edits),
        )

    def _typescript_replacement_preflight_errors(self, edits: List[Dict[str, str]]) -> List[str]:
        ts_edits = [
            edit
            for edit in edits
            if str(edit.get("path", "")).endswith((".ts", ".tsx")) and str(edit.get("content", "")).strip()
        ]
        if not ts_edits:
            return []

        deterministic_errors: List[str] = []
        for edit in ts_edits:
            path = str(edit.get("path", "replacement.ts"))
            findings = _obvious_typescript_text_damage(str(edit.get("content", "")))
            if findings:
                deterministic_errors.append(f"{path}:\n" + "\n".join(findings))
        if deterministic_errors:
            return [
                "Rejected proposal because deterministic TypeScript replacement preflight found stripped operators or TS2314-like bare generics before touching the worktree:\n"
                + "\n\n".join(deterministic_errors)
            ]

        with tempfile.TemporaryDirectory(prefix="logic-port-ts-preflight-") as temp_dir:
            temp_root = Path(temp_dir)
            temp_paths: List[Tuple[str, Path]] = []
            for index, edit in enumerate(ts_edits[:6], start=1):
                source_path = str(edit.get("path", "replacement.ts"))
                suffix = ".tsx" if source_path.endswith(".tsx") else ".ts"
                temp_path = temp_root / f"replacement-{index}{suffix}"
                temp_path.write_text(str(edit.get("content", "")), encoding="utf-8")
                temp_paths.append((source_path, temp_path))

            command = (
                "npx",
                "tsc",
                "--pretty",
                "false",
                "--noEmit",
                "--target",
                "ES2022",
                "--module",
                "ESNext",
                "--moduleResolution",
                "bundler",
                "--skipLibCheck",
                "--noResolve",
                *[str(path) for _source_path, path in temp_paths],
            )
            result = run_command(
                command,
                cwd=self.daemon_config.repo_root,
                timeout_seconds=min(60, max(1, self.daemon_config.command_timeout_seconds)),
            )

        diagnostics = (result.stdout + "\n" + result.stderr).strip()
        if not diagnostics:
            return []
        syntax_lines = []
        for line in diagnostics.splitlines():
            if any(code in line for code in TYPESCRIPT_PREFLIGHT_ERROR_CODES):
                for source_path, temp_path in temp_paths:
                    line = line.replace(str(temp_path), source_path)
                syntax_lines.append(line)
        if not syntax_lines:
            return []
        context = self._typescript_preflight_diagnostic_context(syntax_lines, ts_edits)
        suffix = f"\n\nReplacement diagnostic context:\n{context}" if context else ""
        return [
            "Rejected proposal because TypeScript replacement preflight found parser or generic/type-quality errors before touching the worktree:\n"
            + "\n".join(syntax_lines[:20])
            + suffix
        ]

    def _typescript_preflight_diagnostic_context(self, diagnostics: Sequence[str], edits: Sequence[Dict[str, str]]) -> str:
        edits_by_path = _shared_file_edits_by_path(edits)
        return self._render_typescript_diagnostic_context("\n".join(diagnostics), edits_by_path)

    def _recent_failure_context(self, selected_task: Optional[PlanTask], *, limit: int = 3) -> str:
        if selected_task is None or self.daemon_config.result_log_path is None:
            return "[No recent daemon failure context available.]"
        rows = _read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path))
        return _shared_format_task_result_failure_context(rows, selected_task.label, limit=limit)

    def _selected_task_failure_counts(self, selected_task: Optional[PlanTask]) -> Dict[str, Any]:
        if selected_task is None or self.daemon_config.result_log_path is None:
            return {"total_since_success": 0, "by_kind_since_success": {}}
        rows = _read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path))
        return _current_task_failure_counts(rows, selected_task.label)

    def _relevant_file_context(self, selected_task: Optional[PlanTask], tracked_files: str) -> str:
        return _shared_render_relevant_file_context(
            repo_root=self.daemon_config.repo_root,
            tracked_files=tracked_files,
            task_or_title=selected_task,
            allowed_prefixes=(RUNTIME_LOGIC_PREFIX,),
            suffixes=(".ts", ".tsx", ".json"),
            max_files=self.daemon_config.max_context_files,
            max_file_chars=self.daemon_config.max_context_file_chars,
            preferred_path_fragments=("/cec/", "/tdfol/", "/fol/", "/deontic/"),
            read_text_fn=lambda path: _read_text(path, limit=self.daemon_config.max_context_file_chars),
        )

    def _current_plan_task(self) -> Optional[PlanTask]:
        tasks = self._current_plan_tasks()
        return self._select_next_plan_task(tasks)

    def _current_plan_tasks(self) -> List[PlanTask]:
        if self.daemon_config.task_board_doc is None:
            return []
        path = self.daemon_config.resolve(self.daemon_config.task_board_doc)
        if not path.exists():
            return []
        return extract_plan_tasks(_strip_daemon_task_board(path.read_text(encoding="utf-8")))

    def _rollback_patch(self, patch: str) -> List[CommandResult]:
        check = run_command(
            ("git", "apply", "-R", "--check", "-"),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=self.daemon_config.command_timeout_seconds,
            stdin=patch,
        )
        results = [check]
        if not check.ok:
            return results
        results.append(
            run_command(
                ("git", "apply", "-R", "-"),
                cwd=self.daemon_config.repo_root,
                timeout_seconds=self.daemon_config.command_timeout_seconds,
                stdin=patch,
            )
        )
        return results

    def _persist_failed_patch(self, patch: str, result: CommandResult, *, context: OptimizationContext) -> None:
        path = self.daemon_config.resolve(self.daemon_config.failed_patch_dir)
        path.mkdir(parents=True, exist_ok=True)
        stem = f"{context.session_id}-{int(time.time())}"
        (path / f"{stem}.patch").write_text(patch, encoding="utf-8")
        (path / f"{stem}.json").write_text(json.dumps(result.compact(limit=12000), indent=2), encoding="utf-8")

    def _repair_patch(self, patch: str, result: CommandResult, *, context: OptimizationContext) -> str:
        attempts = max(0, int(self.daemon_config.patch_repair_attempts))
        if attempts <= 0:
            return patch
        repair_prompt = f"""Repair this unified diff so it applies cleanly to the current repository.

Return ONLY JSON with this shape:
{{
  "summary": "short repair description",
  "tasks": ["patch repair"],
  "patch": "corrected unified diff",
  "validation_commands": [["npx", "tsc", "--noEmit"], ["npm", "run", "validate:logic-port"]]
}}

Rules:
- Preserve the original intent.
- Do not add server calls or Python runtime dependencies to browser TypeScript.
- Fix malformed hunk counts, bad context, truncated hunks, and stale file context.
- The patch must be a valid unified diff accepted by git apply.

Session: {context.session_id}
git apply error:
{result.stderr or result.stdout}

Original patch:
{patch}
"""
        try:
            repaired = parse_llm_patch_response(self._call_llm(repair_prompt))
        except Exception as exc:
            LOGGER.warning("patch repair call failed: %s", exc)
            return patch
        if repaired.errors or not repaired.patch.strip():
            return patch
        return repaired.patch

    def _repair_patch_as_files(
        self,
        artifact: LogicPortArtifact,
        result: CommandResult,
        *,
        context: OptimizationContext,
    ) -> LogicPortArtifact:
        attempts = max(0, int(self.daemon_config.file_repair_attempts))
        if attempts <= 0:
            return LogicPortArtifact(raw_response=artifact.raw_response)

        candidate_paths = [
            path
            for path in _artifact_paths(artifact)
            if any(path.startswith(prefix) for prefix in ALLOWED_WRITE_PREFIXES)
        ][:6]
        file_sections: List[str] = []
        for path_text in candidate_paths:
            path = self.daemon_config.resolve(Path(path_text))
            if path.exists() and path.is_file():
                file_sections.append(f"### {path_text}\n```\n{_read_text(path, limit=12000)}\n```")
            else:
                file_sections.append(f"### {path_text}\n[missing file; return complete new file content only if this path should be created]")
        selected_task = self._current_plan_task()
        selected_label = artifact.target_task or (selected_task.label if selected_task else "unknown")

        repair_prompt = f"""The previous daemon proposal produced a malformed unified diff. Convert the same intended change into complete file replacements instead.

Return ONLY JSON with this shape:
{{
  "summary": "short repair description",
  "impact": "how the changed files are directly used by the TypeScript port or validation suite",
  "tasks": {json.dumps(artifact.tasks or ["patch-to-files repair"])},
  "patch": "",
  "files": [
    {{"path": "src/lib/logic/example.ts", "content": "complete replacement file content"}}
  ],
  "validation_commands": [["npx", "tsc", "--noEmit"], ["npm", "run", "validate:logic-port"]]
}}

Rules:
- Do not return another patch.
- Return complete file contents, not snippets.
- Use only paths under src/lib/logic/, docs/, or ipfs_datasets_py/docs/logic/.
- Preserve browser-native TypeScript/WASM behavior with no server or Python runtime dependency.
- Keep the change focused on the daemon-selected task: {selected_label}
- If the task asks for fixture/capture/parity work, include a src/lib/logic/*.test.ts replacement that loads or asserts the fixture content.
- If the task asks for implementation work, include at least one runtime src/lib/logic/ replacement.

Session: {context.session_id}
git apply error:
{result.stderr or result.stdout}

Original summary:
{artifact.summary}

Original impact:
{artifact.impact}

Malformed patch:
{artifact.patch}

Current file contents for likely targets:
{chr(10).join(file_sections) if file_sections else "[No paths could be recovered from the malformed patch.]"}
"""
        try:
            repaired = parse_llm_patch_response(self._call_llm(repair_prompt))
        except Exception as exc:
            LOGGER.warning("patch-to-files repair call failed: %s", exc)
            return LogicPortArtifact(raw_response=artifact.raw_response, errors=[str(exc)])
        if repaired.errors or not repaired.files:
            return repaired
        repaired.files = _repair_common_typescript_file_edits(repaired.files)
        repaired.target_task = artifact.target_task
        return repaired

    def _repair_file_edits_after_preflight(
        self,
        artifact: LogicPortArtifact,
        preflight_errors: Sequence[str],
        *,
        context: OptimizationContext,
        selected_task: Optional[PlanTask],
    ) -> LogicPortArtifact:
        attempts = max(0, int(self.daemon_config.preflight_repair_attempts))
        if attempts <= 0 or not artifact.files:
            return LogicPortArtifact(raw_response=artifact.raw_response)

        task_label = artifact.target_task or (selected_task.label if selected_task else "unknown")
        diagnostic_context = self._typescript_preflight_diagnostic_context(preflight_errors, artifact.files)
        failure_counts = self._selected_task_failure_counts(selected_task)
        repeated_typescript_failures = int(
            failure_counts.get("by_kind_since_success", {}).get("typescript_quality", 0)
            if isinstance(failure_counts, dict)
            else 0
        )
        typescript_quality_budget = max(0, int(self.daemon_config.max_task_typescript_quality_rounds))
        shrink_guidance = ""
        if typescript_quality_budget > 0 and repeated_typescript_failures >= typescript_quality_budget:
            shrink_guidance = (
                "\n- This task has reached the TypeScript-quality failure budget. Do not repair by broadening the same malformed replacement. "
                "Shrink to the smallest compileable browser-native contract for the selected task: one runtime file plus one focused test at most, "
                "simple named interfaces, explicit generic arguments, and no recursive parser rewrites unless the current file already contains that structure."
            )
        repair_prompt = f"""The previous daemon proposal returned complete TypeScript file replacements, but preflight rejected them before touching the worktree.

Repair the same intended change into compileable complete file replacements for the selected task.

Return ONLY JSON with this shape:
{{
  "summary": "short repair description",
  "impact": "how the changed files are directly used by the TypeScript port or validation suite",
  "tasks": {json.dumps(artifact.tasks or ["preflight repair"])},
  "patch": "",
  "files": [
    {{"path": "src/lib/logic/example.ts", "content": "complete replacement file content"}}
  ],
  "validation_commands": [["npx", "tsc", "--noEmit"], ["npm", "run", "validate:logic-port"]]
}}

Rules:
- Do not return a patch. Return complete file contents, not snippets.
- Keep the change focused on the daemon-selected task: {task_label}
- Fix every TypeScript parser/generic diagnostic shown below.
- Do not use bare TypeScript generic aliases. Use Record<string, unknown>, Promise<ResultType>, Omit<Type, Keys>, Map<Key, Value>, and Array<Item> with required type arguments.
- Avoid Omit/Pick when a named interface or explicit options type is simpler and less fragile.
- Every for loop and comparison must include the complete operator and bound expression, such as index < items.length.
- Before returning JSON, inspect the repaired contents for stripped operators or generic arguments such as `index  items.length`, `arity  'Entity'`, `Record =`, `Array =`, `Promise;`, or `Omit;`.
- If a diagnostic points at a complex generated block, shrink that block to a simple compileable fail-closed contract for this task instead of attempting another broad rewrite.
- Preserve public exports already present in the replaced module unless the selected task explicitly removes them.
- Preserve browser-native TypeScript/WASM behavior with no server, Python, filesystem, subprocess, RPC, or Node-only browser-runtime dependency.
- Preserve focused tests for the selected task when tests were part of the original proposal.
{shrink_guidance}

Session: {context.session_id}
Preflight diagnostics:
{chr(10).join(str(error) for error in preflight_errors if error)}

typescript_diagnostic_context={diagnostic_context or '<none>'}

Original summary:
{artifact.summary}

Original impact:
{artifact.impact}

Original files JSON:
{json.dumps(artifact.files, indent=2)}
"""
        repaired = LogicPortArtifact(raw_response=artifact.raw_response)
        for attempt in range(1, attempts + 1):
            self._write_status(
                "preflight_repair_started",
                attempt=attempt,
                attempts=attempts,
                selected_task=task_label,
                session_id=context.session_id,
            )
            try:
                repaired = parse_llm_patch_response(self._call_llm(repair_prompt))
            except Exception as exc:
                LOGGER.warning("preflight repair call failed: %s", exc)
                return LogicPortArtifact(raw_response=artifact.raw_response, errors=[str(exc)], failure_kind="preflight_repair_exception")
            if repaired.errors or not repaired.files:
                continue
            repaired.target_task = artifact.target_task
            repaired.dry_run = artifact.dry_run
            if not repaired.summary:
                repaired.summary = artifact.summary
            if not repaired.impact:
                repaired.impact = artifact.impact
            if not repaired.tasks:
                repaired.tasks = artifact.tasks
            repaired.files = _repair_common_typescript_file_edits(repaired.files)
            return repaired
        return repaired

    def _repair_file_edits_after_validation(self, artifact: LogicPortArtifact, *, context: OptimizationContext) -> LogicPortArtifact:
        attempts = max(0, int(self.daemon_config.validation_repair_attempts))
        if attempts <= 0:
            return LogicPortArtifact(raw_response=artifact.raw_response)

        selected_task = self._current_plan_task()
        selected_label = artifact.target_task or (selected_task.label if selected_task else "unknown")
        if self.daemon_config.validation_repair_failure_budget > 0 and self.daemon_config.result_log_path is not None:
            rows = _read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path))
            repair_failures = int(
                _current_task_failure_counts(rows, selected_label)
                .get("by_kind_since_success", {})
                .get("validation_repair", 0)
            )
            if repair_failures >= self.daemon_config.validation_repair_failure_budget:
                self._write_status(
                    "validation_repair_skipped",
                    selected_task=selected_label,
                    validation_repair_failures_since_success=repair_failures,
                    validation_repair_failure_budget=self.daemon_config.validation_repair_failure_budget,
                )
                return LogicPortArtifact(
                    raw_response=artifact.raw_response,
                    target_task=artifact.target_task,
                    errors=[
                        "Skipped validation repair because this task has repeated validation-repair failures since its last accepted round."
                    ],
                )

        failed_results = [result.compact(limit=12000) for result in artifact.validation_results if not result.ok]
        attempted_files = []
        current_files = []
        for edit in artifact.files[:6]:
            path = str(edit.get("path", ""))
            content = str(edit.get("content", ""))
            attempted_files.append(f"### {path}\n```\n{content[:20000]}\n```")
            resolved = self.daemon_config.resolve(Path(path))
            if path and resolved.exists() and resolved.is_file():
                current_files.append(f"### {path}\n```\n{_read_text(resolved, limit=20000)}\n```")
            elif path:
                current_files.append(f"### {path}\n[missing in repository after rollback]")

        repair_prompt = f"""The daemon applied these complete file replacements, but validation failed and the edits were rolled back.

Return ONLY JSON with corrected complete file replacements.

Required JSON shape:
{{
  "summary": "short repair description",
  "impact": "how the corrected files are directly used by the TypeScript port or validation suite",
  "tasks": {json.dumps(artifact.tasks or [selected_label])},
  "patch": "",
  "files": [
    {{"path": "src/lib/logic/example.ts", "content": "complete replacement file content"}}
  ],
  "validation_commands": [["npx", "tsc", "--noEmit"], ["npm", "run", "validate:logic-port"]]
}}

Rules:
- Do not return a patch.
- Return complete replacement file contents, not snippets.
- Fix the exact validation errors below.
- Base the corrected replacement on the current repository file contents after rollback, not only on the failed attempted replacement.
- Keep the change focused on the daemon-selected task: {selected_label}
- Keep browser runtime changes TypeScript/WASM-native with no Python service or server dependency.
- Use only paths under src/lib/logic/, docs/, or ipfs_datasets_py/docs/logic/.
- Test files must use Jest globals and must not import vitest or @jest/globals.
- Preserve valid TypeScript syntax. Every generic utility type must include required type arguments, for example:
  - Record<string, unknown> instead of Record
  - Pick<T, "key"> instead of Pick
  - Omit<T, "key"> instead of Omit
  - ReadonlySet<string> instead of ReadonlySet
  - Map<string, Value> instead of Map
- If diagnostics are syntax errors such as TS1005, TS1003, TS1128, TS1109, TS1144, or TS1434, repair the smallest syntactic region needed and preserve the surrounding current file structure.
- Do not use Python-style tuple/list/dict syntax, unquoted object keys in type positions, or placeholder ellipses in returned TypeScript.
- Before returning JSON, inspect the corrected contents for stripped operators or generic arguments such as `index  items.length`, `arity  'Entity'`, `Record =`, `Array =`, `Promise;`, or `Omit;`.
- Preserve public exports already present in the replaced module unless the selected task explicitly removes them.

Session: {context.session_id}
Original summary:
{artifact.summary}

Original impact:
{artifact.impact}

Validation failures:
{json.dumps(failed_results, indent=2)}

Attempted file replacements:
{chr(10).join(attempted_files)}

Current repository file contents after rollback:
{chr(10).join(current_files) if current_files else "[No current file contents available.]"}
"""
        self._write_status(
            "validation_repair_started",
            selected_task=selected_label,
            failed_commands=[" ".join(result.command) for result in artifact.validation_results if not result.ok],
        )
        try:
            repaired = parse_llm_patch_response(self._call_llm(repair_prompt))
        except Exception as exc:
            LOGGER.warning("validation repair call failed: %s", exc)
            return LogicPortArtifact(raw_response=artifact.raw_response, errors=[str(exc)])
        if repaired.errors or not repaired.files:
            return repaired
        repaired.files = _repair_common_typescript_file_edits(repaired.files)
        repaired.target_task = artifact.target_task
        return repaired

    def _call_generator_with_deadline(
        self,
        generator: Any,
        *args: Any,
        status_provider: Optional[str],
        **kwargs: Any,
    ) -> str:
        timeout_seconds = float(self.daemon_config.llm_timeout_seconds)

        def record_timeout(elapsed: float, timeout: float, thread_name: str) -> None:
            self._write_status(
                "llm_call_timeout",
                provider=status_provider or "auto",
                timeout_seconds=timeout,
                elapsed_seconds=round(elapsed, 3),
                pending_thread=thread_name,
            )

        def timeout_message(elapsed: float, timeout: float, _thread_name: str) -> str:
            return (
                f"llm_router generation exceeded daemon deadline after {elapsed:.1f}s "
                f"(timeout={timeout:.1f}s, provider={status_provider or 'auto'})"
            )

        return _shared_call_with_thread_deadline(
            generator,
            *args,
            timeout_seconds=timeout_seconds,
            thread_name="logic-port-llm-call",
            on_timeout=record_timeout,
            timeout_message=timeout_message,
            empty_result_message="llm_router generation thread ended without returning a result",
            **kwargs,
        )

    def _call_llm(self, prompt: str) -> str:
        provider = self._resolved_provider()
        self._write_status(
            "llm_call_started",
            model_name=self.daemon_config.model_name,
            provider=provider or "auto",
            timeout_seconds=self.daemon_config.llm_timeout_seconds,
            prompt_chars=len(prompt),
        )
        if self.llm_router is not None:
            generator = getattr(self.llm_router, "generate_text", None)
            if callable(generator):
                text = self._call_generator_with_deadline(
                    generator,
                    prompt,
                    status_provider=provider,
                    provider=provider,
                    model_name=self.daemon_config.model_name,
                    allow_local_fallback=self.daemon_config.allow_local_fallback,
                    max_new_tokens=self.daemon_config.max_new_tokens,
                    temperature=self.daemon_config.temperature,
                    timeout=self.daemon_config.llm_timeout_seconds,
                    trace=bool(self.daemon_config.codex_trace_dir),
                    trace_dir=str(self.daemon_config.resolve(self.daemon_config.codex_trace_dir)) if self.daemon_config.codex_trace_dir else None,
                )
                self._write_status("llm_call_completed", response_chars=len(text))
                return text
            generator = getattr(self.llm_router, "generate", None)
            if callable(generator):
                text = self._call_generator_with_deadline(
                    generator,
                    prompt,
                    status_provider=provider,
                    model_name=self.daemon_config.model_name,
                    max_new_tokens=self.daemon_config.max_new_tokens,
                    temperature=self.daemon_config.temperature,
                    timeout=self.daemon_config.llm_timeout_seconds,
                    trace=bool(self.daemon_config.codex_trace_dir),
                    trace_dir=str(self.daemon_config.resolve(self.daemon_config.codex_trace_dir)) if self.daemon_config.codex_trace_dir else None,
                )
                self._write_status("llm_call_completed", response_chars=len(text))
                return text

        try:
            text = call_llm_router(
                prompt,
                LlmRouterInvocation(
                    repo_root=self.daemon_config.repo_root,
                    model_name=self.daemon_config.model_name,
                    provider=provider,
                    allow_local_fallback=self.daemon_config.allow_local_fallback,
                    timeout_seconds=int(self.daemon_config.llm_timeout_seconds),
                    max_new_tokens=self.daemon_config.max_new_tokens,
                    max_prompt_chars=self.daemon_config.max_prompt_chars,
                    temperature=self.daemon_config.temperature,
                    env_prefix="LOGIC_PORT_DAEMON_LLM",
                    prompt_file_prefix="logic-port-llm-prompt-",
                    python_executable=sys.executable,
                    trace=bool(self.daemon_config.codex_trace_dir),
                    trace_dir=self.daemon_config.resolve(self.daemon_config.codex_trace_dir)
                    if self.daemon_config.codex_trace_dir
                    else None,
                ),
            )
        except Exception as exc:
            self._write_status("llm_call_failed", error=str(exc), provider=provider or "auto")
            raise RuntimeError(
                f"llm_router could not generate with model={self.daemon_config.model_name!r} "
                f"provider={provider or 'auto'!r}. Configure the provider credentials or pass --provider. "
                f"Original error: {exc}"
            ) from exc
        self._write_status("llm_call_completed", response_chars=len(text), provider=provider or "auto")
        return text

    def _resolved_provider(self) -> Optional[str]:
        if self.daemon_config.provider:
            return self.daemon_config.provider
        return None

    def _build_prompt(self, *, input_data: Any, context: OptimizationContext) -> str:
        budget = self.daemon_config.max_prompt_chars
        plan_tasks: List[PlanTask] = []
        source_docs: List[Tuple[Path, Path, str]] = []
        task_board_resolved = (
            self.daemon_config.resolve(self.daemon_config.task_board_doc)
            if self.daemon_config.task_board_doc is not None
            else None
        )
        for path in [*self.daemon_config.plan_docs, *self.daemon_config.status_docs]:
            resolved = self.daemon_config.resolve(path)
            if not resolved.exists():
                continue
            text = resolved.read_text(encoding="utf-8")
            source_docs.append((path, resolved, text))
            if task_board_resolved is not None and resolved == task_board_resolved:
                plan_tasks = extract_plan_tasks(_strip_daemon_task_board(text))

        selected_task = self._select_next_plan_task(plan_tasks)
        selected_task_text = selected_task.label if selected_task else "No markdown task could be selected."
        doc_sections = []
        for path, resolved, text in source_docs:
            if task_board_resolved is not None and resolved == task_board_resolved:
                rendered = _focused_task_board_excerpt(text, selected_task, limit=max(4000, budget // 5))
            else:
                rendered = _truncate_text(text, limit=max(1200, budget // 10))
            doc_sections.append(f"## {path}\n{rendered}")

        git_status = run_command(
            ("git", "status", "--short"),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=30,
        )
        file_inventory = run_command(
            ("git", "ls-files", str(self.daemon_config.typescript_logic_dir), str(self.daemon_config.python_logic_dir)),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=30,
        )
        recent_failure_context = self._recent_failure_context(selected_task)
        task_failure_counts = self._selected_task_failure_counts(selected_task)
        repeated_typescript_failures = int(task_failure_counts.get("by_kind_since_success", {}).get("typescript_quality", 0))
        prompt_rows: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        if self.daemon_config.result_log_path is not None:
            prompt_rows = _read_daemon_results(self.daemon_config.resolve(self.daemon_config.result_log_path))
        rollback_quality_failures = _rollback_quality_failure_counts(prompt_rows)
        repeated_rollback_failures = int(rollback_quality_failures.get("consecutive", 0))
        slice_mode = self.daemon_config.slice_mode if self.daemon_config.slice_mode in {"small", "balanced", "broad"} else "balanced"
        typescript_quality_budget = max(0, int(self.daemon_config.max_task_typescript_quality_rounds))
        effective_slice_mode = slice_mode
        if (
            slice_mode == "balanced"
            and typescript_quality_budget > 0
            and repeated_typescript_failures >= typescript_quality_budget
        ):
            effective_slice_mode = "small"
        if effective_slice_mode == "small":
            slice_guidance = (
                "Slice mode: small. Prefer one implementation file plus one focused test file, and keep the diff as compact as possible."
            )
        elif effective_slice_mode == "broad":
            slice_guidance = (
                "Slice mode: broad. Prefer a complete coherent parity chunk for the selected task; it may span 2-5 related runtime/test files "
                "when that is necessary for browser-native behavior, but it must still stay compileable and under the diff-line budget."
            )
        else:
            slice_guidance = (
                "Slice mode: balanced. Prefer a useful vertical slice for the selected task, usually 1-3 related implementation/test files, "
                "so the result is directly exercised by validation without becoming a broad rewrite."
        )
        recovery_mode_context = "[No repeated TypeScript-quality failure recovery mode active.]"
        if repeated_typescript_failures >= 2:
            if effective_slice_mode == "small":
                recovery_mode_context = (
                    f"Repeated TypeScript-quality failures for this task: {repeated_typescript_failures}. "
                    "Recovery mode is active: land the smallest compileable TypeScript contract first, avoid large feature-complete files, "
                    "avoid advanced generic types, avoid custom JSON recursive unions unless already present in the current file, "
                    "and include only one focused test that proves the contract. Prefer simple interfaces, string/number/boolean/null arrays/records, "
                    "and fail-closed stubs that can be expanded in later tasks."
                )
                if slice_mode != effective_slice_mode:
                    recovery_mode_context += (
                        f" Balanced slice mode was overridden to small because this task reached the "
                        f"TypeScript-quality failure budget of {typescript_quality_budget}; do not attempt another full-module replacement."
                    )
            elif effective_slice_mode == "broad":
                recovery_mode_context = (
                    f"Repeated TypeScript-quality failures for this task: {repeated_typescript_failures}. "
                    "Recovery mode is active, but broad slice mode should not collapse the work into a tiny placeholder. "
                    "Land one compileable multi-file parity chunk for the daemon-selected task when the task naturally needs it, "
                    "avoid advanced generic types and fragile recursive JSON unions, and include focused tests that exercise the runtime contract."
                )
            else:
                recovery_mode_context = (
                    f"Repeated TypeScript-quality failures for this task: {repeated_typescript_failures}. "
                    "Recovery mode is active, but balanced slice mode should still land a useful vertical slice rather than a tiny scaffold. "
                    "Implement one coherent browser-native contract for the selected task, typically with 1-3 related implementation/test files, "
                    "avoid advanced generic types and fragile recursive JSON unions, and include focused tests that exercise the runtime behavior."
                )
        if repeated_rollback_failures >= 3:
            recovery_mode_context += (
                "\nUnattended rollback recovery mode is active because recent daemon rounds have rolled back without accepted files: "
                f"{repeated_rollback_failures} consecutive rollback-quality failures. For this cycle, prioritize a smaller compileable scaffold "
                "over a feature-complete replacement: one runtime source file plus one focused test at most, simple named interfaces, explicit "
                "generic arguments, and no broad module rewrites. Preserve existing exports used by neighboring files, especially when replacing "
                "an existing module."
            )
        relevant_file_context = self._relevant_file_context(selected_task, file_inventory.stdout)
        blocked_backlog_context = "[No blocked backlog context available.]"
        if self.daemon_config.task_board_doc is not None:
            blocked_backlog_context = self._blocked_task_backlog_markdown(plan_tasks, prompt_rows)

        prompt = f"""You are implementing the browser-native TypeScript/WASM port of ipfs_datasets_py logic.

Use the TypeScript port plan as the controlling roadmap. The deterministic parser plans are not this daemon's task ledger.
Goal: improve parity with the Python logic module while preserving browser-native runtime constraints.

Hard constraints:
- Do not add server-side runtime calls to the TypeScript logic library.
- Do not wrap Python services from browser code.
- Do not add Node-only, Rust FFI, filesystem, subprocess, RPC, or server fallbacks to browser runtime code.
- Prefer deterministic TypeScript or WASM-compatible implementations.
- For tasks phrased "where feasible", land the feasible browser-native contract, metadata, validation, or fail-closed adapter first when a real cryptographic/WASM implementation is not already available in the project.
- Preserve existing tests and add focused tests for each change.
- Use the existing Jest test harness. Test files should rely on global describe/it/expect and must not import vitest or @jest/globals.
- Prefer adding cases to an existing matching *.test.ts file over creating a new test file.
- Prefer the JSON `files` array with complete replacement file contents. For this daemon run, `files` is the primary output channel because it produces auditable changed files and avoids malformed patch cycles.
- Leave `patch` empty unless a complete file replacement would be unsafe or impossible.
- The Codex subprocess may run in a read-only sandbox. That only prevents the subprocess from editing files directly; it does not prevent this daemon from applying the JSON `files` replacements that you return. Never refuse because of a read-only sandbox.
- Do not run exploratory shell commands in the Codex subprocess. Use the current file context below and return the JSON proposal promptly so the 300 second daemon timeout is spent on implementation, not browsing.
- Do not include shell commands that mutate files.
- Do not use bare TypeScript generic aliases. Always spell `Record<string, unknown>`, `Promise<ResultType>`, `Omit<Type, Keys>`, `Map<Key, Value>`, and `Array<Item>` with every required type argument.
- For loop and comparison expressions must use complete operators such as `<`, `<=`, `>`, `>=`, `===`, and `!==`; never omit the operator around bounds checks.
- Before returning JSON, inspect the file contents you are about to return for stripped operators or generic arguments: reject your own answer if it contains fragments like `index  items.length`, `while (offset  text.length`, `arity  'Entity'`, `Record =`, `Array =`, `Promise;`, or `Omit;`.
- When replacing an existing TypeScript module, preserve public exports that neighboring files import unless the selected task explicitly removes them.
- Use conservative, PR-sized changes.
- Choose one narrow requirement per cycle.
- The daemon-selected task for this cycle is: {selected_task_text}
- Follow the slice mode guidance below; recovery mode should keep changes compileable without shrinking below the selected task's useful parity boundary.
- Work only on that daemon-selected task unless the repository already satisfies it; if it is already satisfied, update docs/tests for that task rather than jumping ahead.
- Prefer implementation changes under src/lib/logic/ whenever the selected task asks for functionality, not only docs.
- Fixture-only work is acceptable only when the selected port-plan checkbox explicitly asks for fixtures or generated Python parity captures.
- For accepted work, the changed files must be directly usable by the TypeScript port validation suite.
- For implementation tasks, include at least one runtime source change under src/lib/logic/; docs-only, board-only, or parity-fixture-only changes are not acceptable.
- For fixture/capture tasks, include tests that load and assert the fixture content so the work is used by validation.
- Fixture/capture/parity proposals that do not update a src/lib/logic/*.test.ts file will be rejected.
- Explain the concrete impact of the changed files in the JSON impact field.
- Limit the patch to at most {self.daemon_config.max_patch_lines} changed diff lines.
- {slice_guidance}
- Do not include prose inside the patch string. When using `files`, include the full file content exactly as it should exist after the edit.
- Generate the patch against the exact current file contents shown by repository status and tracked-file inventory.
- Use valid unified-diff hunk headers and include enough unchanged context for git apply.
- If you cannot produce a patch that git apply will accept, return an empty patch with a clear summary.

Return ONLY JSON with this shape:
{{
  "summary": "short description",
  "impact": "how the changed files are directly used by the TypeScript port or its validation suite",
  "tasks": ["requirement addressed"],
  "patch": "unified diff string, or empty if using files",
  "files": [
    {{"path": "src/lib/logic/example.ts", "content": "complete replacement file content"}}
  ],
  "validation_commands": [["npx", "tsc", "--noEmit"], ["npm", "run", "validate:logic-port"]]
}}

Prefer "files" over "patch" for TypeScript/doc changes. Use complete file contents, not snippets.
Set `"patch": ""` whenever you provide `files`.
Only use paths under src/lib/logic/, docs/, or ipfs_datasets_py/docs/logic/.
Session: {context.session_id}
Model requested by daemon: {self.daemon_config.model_name}
Provider requested by daemon: {self._resolved_provider() or "auto"}
Slice mode requested by daemon: {slice_mode}
Effective slice mode for this task: {effective_slice_mode}
Dry run: {self.daemon_config.dry_run}

Current git status:
{git_status.stdout}
{git_status.stderr}

Relevant tracked files:
{file_inventory.stdout[-12000:]}

Recent daemon failures for the selected task:
{recent_failure_context}

Task recovery mode:
{recovery_mode_context}

Blocked backlog context:
{blocked_backlog_context}

Relevant current file contents:
{relevant_file_context}

Documents:
{chr(10).join(doc_sections)}
"""
        if len(prompt) > budget:
            return prompt[:budget] + "\n\n[daemon prompt truncated]\n"
        return prompt

    def _run_validation(self) -> List[CommandResult]:
        results: List[CommandResult] = []
        for command in self.daemon_config.validation_commands:
            results.append(
                run_command(
                    command,
                    cwd=self.daemon_config.repo_root,
                    timeout_seconds=self.daemon_config.command_timeout_seconds,
                )
            )
            if not results[-1].ok:
                break
        return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Iteratively improve the TypeScript ipfs_datasets_py logic port.")
    auto_commit_default = os.environ.get("LOGIC_PORT_DAEMON_AUTO_COMMIT", "1").strip().lower() not in {"0", "false", "no", "off"}
    auto_commit_startup_dirty_default = (
        os.environ.get("LOGIC_PORT_DAEMON_AUTO_COMMIT_STARTUP_DIRTY", "1").strip().lower()
        not in {"0", "false", "no", "off"}
    )
    parser.add_argument("--repo-root", default=".", help="Repository root containing package.json and ipfs_datasets_py/")
    parser.add_argument("--model", default="gpt-5.5", help="llm_router model name")
    parser.add_argument("--provider", default=None, help="Optional llm_router provider")
    parser.add_argument(
        "--proposal-transport",
        choices=("llm_router", "router", "router-json", "patch", "hybrid", "worktree", "patchless", "direct-edit"),
        default=os.environ.get("LOGIC_PORT_DAEMON_PROPOSAL_TRANSPORT", "worktree"),
        help=(
            "How to obtain candidate changes. worktree lets Codex edit an isolated Git worktree "
            "and the daemon harvests file replacements/diffs; llm_router uses legacy JSON files/patch proposals."
        ),
    )
    parser.add_argument(
        "--worktree-edit-timeout",
        "--worktree-edit-timeout-seconds",
        dest="worktree_edit_timeout",
        type=int,
        default=int(os.environ.get("LOGIC_PORT_DAEMON_WORKTREE_EDIT_TIMEOUT_SECONDS", "300")),
        help="Timeout for isolated-worktree direct-edit proposal generation.",
    )
    parser.add_argument(
        "--worktree-stale-after",
        "--worktree-stale-after-seconds",
        dest="worktree_stale_after",
        type=int,
        default=int(os.environ.get("LOGIC_PORT_DAEMON_WORKTREE_STALE_AFTER_SECONDS", "7200")),
        help="Age after which dead daemon-created worktrees are pruned.",
    )
    parser.add_argument(
        "--worktree-codex-sandbox",
        default=os.environ.get(
            "LOGIC_PORT_DAEMON_WORKTREE_CODEX_SANDBOX",
            os.environ.get("IPFS_DATASETS_PY_CODEX_SANDBOX", "danger-full-access"),
        ),
        help="Codex sandbox mode used for direct-edit proposal worktrees.",
    )
    parser.add_argument(
        "--worktree-root",
        default=os.environ.get("LOGIC_PORT_DAEMON_WORKTREE_ROOT", "ipfs_datasets_py/.daemon/logic-port-worktrees"),
        help="Directory for throwaway direct-edit Git worktrees.",
    )
    parser.add_argument(
        "--codex-bin",
        default=os.environ.get("CODEX_BIN", "codex"),
        help="Codex executable used by worktree/direct-edit proposal transport.",
    )
    parser.add_argument(
        "--worktree-repair-attempts",
        type=int,
        default=int(os.environ.get("LOGIC_PORT_DAEMON_WORKTREE_REPAIR_ATTEMPTS", "1")),
        help="Worktree direct-edit repair attempts after a worktree candidate fails validation before falling back to legacy JSON repair.",
    )
    parser.set_defaults(auto_commit=auto_commit_default, auto_commit_startup_dirty=auto_commit_startup_dirty_default)
    parser.add_argument(
        "--auto-commit",
        dest="auto_commit",
        action="store_true",
        help="Commit validated daemon-owned TypeScript/docs changes to the current main branch after accepted rounds.",
    )
    parser.add_argument(
        "--no-auto-commit",
        dest="auto_commit",
        action="store_false",
        help="Leave validated daemon changes uncommitted after accepted rounds.",
    )
    parser.add_argument(
        "--auto-commit-startup-dirty",
        dest="auto_commit_startup_dirty",
        action="store_true",
        help="Before each supervised cycle, commit dirty daemon-owned TypeScript/port-plan files on main.",
    )
    parser.add_argument(
        "--no-auto-commit-startup-dirty",
        dest="auto_commit_startup_dirty",
        action="store_false",
        help="Do not commit pre-existing dirty daemon-owned files at supervised-cycle start.",
    )
    parser.add_argument(
        "--auto-commit-branch",
        default=os.environ.get("LOGIC_PORT_DAEMON_AUTO_COMMIT_BRANCH", "main"),
        help="Branch name required for daemon auto-commits; set empty to allow the current branch.",
    )
    parser.add_argument(
        "--slice-mode",
        choices=("small", "balanced", "broad"),
        default="balanced",
        help="How much work the daemon should ask for per LLM cycle; balanced keeps recovery compileable without forcing tiny scaffolds.",
    )
    parser.add_argument("--iterations", type=int, default=1, help="Maximum daemon iterations")
    parser.add_argument("--interval", type=float, default=0.0, help="Seconds to sleep between iterations")
    parser.add_argument("--apply", action="store_true", help="Apply model-generated patches. Default is dry-run.")
    parser.add_argument("--watch", action="store_true", help="Run continuously without user input.")
    parser.add_argument("--cycles", type=int, default=0, help="Cycles for --watch; 0 means unlimited.")
    parser.add_argument("--retry-interval", type=float, default=0.0, help="Seconds between supervised daemon cycles. Default 0 starts the next cycle immediately.")
    parser.add_argument("--max-failure-cycles", type=int, default=0, help="Stop --watch after N failed cycles; 0 means unlimited.")
    parser.add_argument("--max-task-failures", type=int, default=6, help="Block the current task after N failures since its last accepted round, regardless of failure kind.")
    parser.add_argument(
        "--max-task-typescript-quality-failures",
        type=int,
        default=3,
        help="Block or shrink a task after N TypeScript-quality failures since its last accepted round; 0 disables this dedicated budget.",
    )
    parser.add_argument("--llm-timeout", type=int, default=300, help="Seconds before a single LLM/Codex call times out.")
    parser.add_argument("--command-timeout", type=int, default=300, help="Seconds before validation/git commands time out.")
    parser.add_argument("--max-prompt-chars", type=int, default=32000, help="Maximum prompt characters sent to a single LLM/Codex call.")
    parser.add_argument("--log-file", default=None, help="Optional file for JSON results from each daemon invocation.")
    parser.add_argument("--status-file", default=None, help="Optional heartbeat/status JSON file. Defaults to .daemon status path.")
    parser.add_argument("--progress-file", default=None, help="Optional progress summary JSON file. Defaults to .daemon progress path.")
    parser.add_argument("--heartbeat-interval", type=float, default=30.0, help="Seconds between status heartbeat writes while a cycle is active.")
    parser.add_argument("--file-repair-attempts", type=int, default=1, help="Attempts to convert malformed patches into complete file replacements.")
    parser.add_argument("--preflight-repair-attempts", type=int, default=1, help="Attempts to repair complete file replacements rejected by TypeScript preflight before failing the round.")
    parser.add_argument("--validation-repair-attempts", type=int, default=1, help="Attempts to repair complete file replacements after validation errors.")
    parser.add_argument(
        "--validation-repair-failure-budget",
        type=int,
        default=2,
        help="Skip validation-repair LLM calls for a task after this many validation-repair failures since its last accepted round; 0 disables the adaptive skip.",
    )
    parser.add_argument("--proposal-attempts", type=int, default=3, help="LLM proposal attempts per daemon cycle before logging a failed round.")
    parser.add_argument("--revisit-blocked-tasks", action="store_true", help="When no needed/in-progress tasks remain, intentionally select blocked port-plan tasks for another autonomous attempt.")
    parser.add_argument("--blocked-backlog-limit", type=int, default=10, help="Number of blocked tasks to summarize in progress, prompts, and the generated task board.")
    parser.add_argument(
        "--blocked-task-strategy",
        choices=("plan-order", "fewest-failures", "most-failures"),
        default="plan-order",
        help="Blocked-task selection strategy used with --revisit-blocked-tasks.",
    )
    parser.add_argument("--no-plan-replenishment", action="store_true", help="Disable automatic plan replenishment when no eligible tasks remain.")
    parser.add_argument("--plan-replenishment-limit", type=int, default=12, help="Maximum implementation-plan tasks to add during one automatic code-state replenishment pass.")
    parser.add_argument("--skip-validation", action="store_true", help="Do not run validation commands")
    parser.add_argument("--validation-command", action="append", default=[], help="Validation command, shell-split by spaces")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    validation_commands: Tuple[Tuple[str, ...], ...]
    if args.skip_validation:
        validation_commands = tuple()
    elif args.validation_command:
        validation_commands = tuple(tuple(command.split()) for command in args.validation_command)
    else:
        validation_commands = DEFAULT_VALIDATION_COMMANDS

    config = LogicPortDaemonConfig(
        repo_root=Path(args.repo_root).resolve(),
        model_name=args.model,
        provider=args.provider,
        slice_mode=args.slice_mode,
        max_iterations=max(1, args.iterations),
        interval_seconds=max(0.0, args.interval),
        dry_run=not args.apply,
        validation_commands=validation_commands,
        max_prompt_chars=max(4000, args.max_prompt_chars),
        llm_timeout_seconds=max(1, args.llm_timeout),
        command_timeout_seconds=max(1, args.command_timeout),
        proposal_transport=str(args.proposal_transport),
        worktree_edit_timeout_seconds=max(1, args.worktree_edit_timeout),
        worktree_stale_after_seconds=max(1, args.worktree_stale_after),
        worktree_codex_sandbox=str(args.worktree_codex_sandbox),
        worktree_root=Path(args.worktree_root),
        codex_bin=str(args.codex_bin),
        worktree_repair_attempts=max(0, args.worktree_repair_attempts),
        auto_commit=bool(args.auto_commit),
        auto_commit_branch=str(args.auto_commit_branch),
        auto_commit_startup_dirty=bool(args.auto_commit_startup_dirty),
        retry_interval_seconds=max(0.0, args.retry_interval),
        max_failure_cycles=max(0, args.max_failure_cycles),
        max_task_total_failure_rounds=max(0, args.max_task_failures),
        max_task_typescript_quality_rounds=max(0, args.max_task_typescript_quality_failures),
        result_log_path=Path(args.log_file) if args.log_file else None,
        status_path=Path(args.status_file) if args.status_file else Path("ipfs_datasets_py/.daemon/logic-port-daemon.status.json"),
        progress_path=Path(args.progress_file) if args.progress_file else Path("ipfs_datasets_py/.daemon/logic-port-daemon.progress.json"),
        heartbeat_interval_seconds=max(0.0, args.heartbeat_interval),
        file_repair_attempts=max(0, args.file_repair_attempts),
        preflight_repair_attempts=max(0, args.preflight_repair_attempts),
        validation_repair_attempts=max(0, args.validation_repair_attempts),
        validation_repair_failure_budget=max(0, args.validation_repair_failure_budget),
        proposal_attempts=max(1, args.proposal_attempts),
        revisit_blocked_tasks=bool(args.revisit_blocked_tasks),
        blocked_backlog_limit=max(0, args.blocked_backlog_limit),
        blocked_task_strategy=args.blocked_task_strategy,
        replenish_plan_when_empty=not bool(args.no_plan_replenishment),
        plan_replenishment_limit=max(0, args.plan_replenishment_limit),
    )
    optimizer = LogicPortDaemonOptimizer(config)
    results = optimizer.run_supervised(cycles=max(0, args.cycles)) if args.watch else optimizer.run_daemon()
    if args.log_file and not args.watch:
        optimizer._append_result_log(results)
    print(json.dumps(results, indent=2, default=str))
    return 0 if results and bool(results[-1].get("valid")) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
