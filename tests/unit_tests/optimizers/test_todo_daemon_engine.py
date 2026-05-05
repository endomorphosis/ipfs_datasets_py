from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ipfs_datasets_py.optimizers.todo_daemon import (
    ACCEPTED_WORK_LEDGER_SCHEMA_VERSION,
    AcceptedWorkEvidencePaths,
    ActiveStatusSnapshot,
    AutoCommitConfig,
    CommandResult,
    DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
    FailureBlockRule,
    FileReplacementHooks,
    FileReplacementTodoDaemonRunner,
    LifecycleWrapperSpec,
    LlmRouterInvocation,
    LifecycleWrapperScriptSpec,
    ManagedDaemonSpec,
    PathPolicy,
    PlanTask,
    PreTaskBlock,
    Proposal,
    ProposalPreflightPolicy,
    RestartPolicy,
    SupervisedChildSpec,
    SupervisorLoop,
    SupervisorLoopConfig,
    Task,
    TodoDaemonHooks,
    TodoDaemonRunner,
    TodoDaemonRegistration,
    TodoDaemonRuntimeConfig,
    ValidationWorkspaceSpec,
    AcceptedWorkPersistenceResult,
    WorkSidecarPaths,
    accepted_work_evidence_manifest,
    accepted_work_manifest,
    accepted_work_markdown_entry,
    accepted_work_workspace_payload,
    advance_active_status_snapshot,
    append_jsonl,
    append_accepted_work_ledger,
    append_accepted_work_markdown_log,
    apply_file_replacement_proposal,
    attempt_file_replacement_validation_repair,
    append_jsonl_ledger,
    artifact_string_items,
    artifact_validation_text,
    as_repo_path,
    auto_commit_paths,
    block_threshold_for_failure_kind,
    blocked_task_backlog_markdown,
    build_auto_commit_subject,
    build_accepted_work_ledger_entry,
    build_proposal_accepted_work_ledger_entry,
    build_scoped_accepted_work_ledger_entry,
    build_blocked_task_backlog,
    build_deterministic_progress_record,
    build_deterministic_replacement_proposal,
    build_file_replacement_apply_proposal,
    build_file_replacement_retry_prompt,
    build_file_replacement_validation_repair_prompt,
    build_lifecycle_arg_parser,
    build_active_status_payload,
    build_heartbeat_status_payload,
    build_ready_after_supervisor_repair_status,
    build_python_module_command,
    build_restart_loop_command,
    build_status_phase_key,
    build_supervisor_loop_arg_parser,
    build_supervisor_status_payload,
    build_todo_runner_arg_parser,
    build_validation_workspace_spec,
    call_llm_router,
    call_with_thread_deadline,
    canonical_daemon_names,
    clear_child_pid_file,
    classify_artifact_failure_kind,
    cleanup_stale_daemon_worktrees,
    command_runner_from_legacy_function,
    command_result_from_object,
    command_results_from_objects,
    compact_status_artifact,
    compact_validation_result,
    compact_validation_results,
    config_promote_worktree_files,
    config_proposal_diff_from_worktree,
    config_repo_root,
    config_verify_promoted_worktree_files,
    count_proposal_records_with_failure_markers,
    count_recent_proposal_failures,
    count_unmanaged_generated_status_sections,
    current_task_failure_counts,
    dataclass_worktree_config,
    daemon_alias_map,
    daemon_registry_payload,
    daemon_spec_payload,
    default_lifecycle_wrapper_script_specs,
    diagnostic_signatures,
    exception_diagnostic,
    dispatcher_choices,
    env_flag,
    env_float,
    env_int,
    env_path,
    env_path_in_dir,
    env_value,
    extract_codex_event_text_candidates,
    extract_json,
    extract_plan_tasks,
    fallback_kind_for_task,
    failed_work_manifest,
    failed_work_workspace_payload,
    file_edits_by_path,
    first_present,
    format_recent_failure_context,
    format_task_result_failure_context,
    first_failure_block_decision,
    first_open_plan_task,
    focused_task_board_excerpt,
    generated_status_block,
    heartbeat_snapshot,
    has_diagnostic_codes,
    is_retryable_proposal_failure,
    launch_supervised_child,
    last_task_attempt_index,
    lifecycle_wrapper_core_lines,
    lifecycle_wrapper_matches_rendered,
    lifecycle_wrapper_payload,
    lifecycle_wrapper_script_payload,
    load_deterministic_progress_manifest,
    load_daemon_main,
    looks_like_empty_codex_event_stream,
    managed_status_block_pattern,
    markdown_task_label,
    materialize_proposal_files,
    match_diagnostic_edit_path,
    managed_git_worktree,
    missing_lifecycle_wrapper_core_lines,
    normalize_file_edits,
    normalize_string_item_lists,
    normalize_string_items,
    normalize_task_references,
    normalize_validation_commands,
    obvious_typescript_text_damage,
    owner_pid_from_worktree,
    open_task_has_deterministic_fallback,
    parse_file_replacement_response,
    parse_json_proposal,
    parse_markdown_tasks,
    persist_proposal_accepted_work,
    persist_proposal_failed_work,
    plan_task_from_latest_result,
    paths_from_file_edits,
    paths_from_git_status_porcelain,
    paths_from_patch_and_file_edits,
    paths_from_unified_diff,
    paths_include_required_change,
    prompt_limit_for_mode,
    proposal_block_threshold,
    proposal_diff_from_worktree,
    proposal_error_text,
    preflight_proposal_payload,
    promote_worktree_files,
    proposal_record_has_failure_markers,
    quality_failure_counts,
    quoted_env_assignments,
    read_daemon_results,
    read_daemon_proposal_records,
    read_json_object,
    repair_common_typescript_file_edits,
    repair_common_typescript_text_damage,
    repo_relative_copy_paths,
    repo_relative_pathspec,
    recent_failure_count,
    recent_proposal_failures,
    recent_rollback_failure_count,
    recent_total_failure_count,
    replace_task_mark,
    resolve_artifact_directory,
    resolve_daemon_module,
    restarting_wrapper_alive,
    rank_relevant_context_file,
    repo_root_from_env,
    render_relevant_file_context,
    render_lifecycle_wrapper,
    render_file_edit_diagnostic_context,
    render_proposal_feedback,
    resolve_artifact_directory,
    render_typescript_diagnostic_context,
    rollback_failure_counts,
    rounds_since_last_valid,
    run_command,
    run_validation_commands,
    run_lifecycle_args,
    run_lifecycle_cli,
    run_supervisor_loop_cli,
    supervisor_loop_config_from_args,
    supervisor_loop_result_payload,
    run_todo_daemon,
    run_todo_daemon_cli,
    safe_auto_commit_pathspecs,
    select_task,
    select_blocked_plan_task,
    select_next_plan_task,
    select_relevant_context_paths,
    should_skip_validation_for_empty_proposal,
    should_sleep_between_task_cycles,
    should_use_compact_prompt_for_failures,
    sidecar_paths,
    slugify,
    slugify_artifact_name,
    status_key_started_at,
    status_started_at,
    strip_unmanaged_generated_status_sections,
    supervised_log_path,
    supervisor_maintenance_snapshot,
    supervisor_run_id,
    task_failure_summary,
    task_has_deterministic_fallback,
    task_title_contains_any,
    task_status_counts,
    task_title_tokens,
    temporary_validation_worktree,
    timestamped_artifact_base,
    todo_daemon_proposals_payload,
    truncate_text,
    tranche_number_from_title,
    unified_diff_stats,
    unique_normalized_paths,
    untracked_paths_from_git_status_porcelain,
    update_generated_status_block,
    upsert_deterministic_progress_record,
    validation_commands_for_proposal,
    validation_command_summaries,
    validation_worktree_for_spec,
    verify_promoted_worktree_files,
    wait_for_child_exit,
    worktree_phase_worker_status,
    write_json,
    write_accepted_work_evidence_artifacts,
    write_status_json,
    write_work_sidecars,
    write_worktree_owner_file,
)
from ipfs_datasets_py.optimizers.todo_daemon.__main__ import (
    daemon_names,
    main as todo_daemon_package_main,
)


@dataclass
class SyntheticDaemonConfig:
    repo_root: Path
    task_board: Path = Path("todo/board.md")
    status_file: Path = Path("todo/status.json")
    progress_file: Path = Path("todo/progress.json")
    result_log: Path = Path("todo/results.jsonl")
    apply: bool = True
    watch: bool = False
    iterations: int = 1
    interval_seconds: float = 0.0
    heartbeat_seconds: float = 30.0
    crash_backoff_seconds: float = 0.0
    revisit_blocked: bool = False

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path


def test_parse_markdown_tasks_and_select_reuses_checkbox_ids() -> None:
    tasks = parse_markdown_tasks(
        "\n".join(
            [
                "- [x] Task checkbox-7: Already done.",
                "- [!] Task checkbox-8: Protected blocked.",
                "- [ ] Task checkbox-9: Next reusable task.",
            ]
        )
    )

    selected = select_task(tasks, revisit_blocked=True, protected_blocked_checkbox_ids={8})

    assert selected is not None
    assert selected.checkbox_id == 9
    assert selected.label == "Task checkbox-9: Next reusable task."


def test_task_board_generated_status_helpers_are_reusable() -> None:
    tasks = parse_markdown_tasks(
        "\n".join(
            [
                "- [ ] Task checkbox-1: Needed.",
                "- [~] Task checkbox-2: Active.",
                "- [x] Task checkbox-3: Done.",
                "- [!] Task checkbox-4: Blocked.",
            ]
        )
    )
    markdown = "\n".join(
        [
            "# Board",
            "",
            "## Generated Status",
            "",
            "stale",
            "",
            "- [ ] Task checkbox-1: Needed.",
        ]
    )

    updated = update_generated_status_block(
        markdown,
        latest={"target_task": tasks[0].label, "result": "valid", "summary": "accepted"},
        tasks=tasks,
        start_marker="<!-- daemon:start -->",
        end_marker="<!-- daemon:end -->",
        now=lambda: "2026-01-01T00:00:00Z",
    )

    assert task_status_counts(tasks) == {
        "needed": 1,
        "in_progress": 1,
        "complete": 1,
        "blocked": 1,
    }
    assert count_unmanaged_generated_status_sections(
        updated,
        start_marker="<!-- daemon:start -->",
        end_marker="<!-- daemon:end -->",
    ) == 0
    assert "<!-- daemon:start -->" in updated
    assert "Latest result: `valid`" in updated
    assert "stale" not in updated


def test_task_board_mark_and_watch_sleep_helpers_are_reusable() -> None:
    markdown = "\n".join(
        [
            "- [x] Task checkbox-1: Done.",
            "- [!] Task checkbox-2: Blocked.",
            "- [ ] Task checkbox-3: Needed.",
        ]
    )
    tasks = parse_markdown_tasks(markdown)

    updated = replace_task_mark(markdown, tasks[2], "~")
    complete = replace_task_mark(updated, tasks[2], "x")

    assert "- [~] Task checkbox-3: Needed." in updated
    assert not should_sleep_between_task_cycles(markdown)
    assert should_sleep_between_task_cycles(complete, revisit_blocked=False)
    assert should_sleep_between_task_cycles(
        complete,
        revisit_blocked=True,
        protected_blocked_checkbox_ids={2},
    )
    assert not should_sleep_between_task_cycles(
        complete,
        revisit_blocked=True,
        protected_blocked_checkbox_ids=set(),
    )


def test_task_board_focused_excerpt_helpers_are_reusable() -> None:
    markdown = "\n".join(
        [
            "# Board",
            "- [ ] Task checkbox-1: Alpha task.",
            "alpha details",
            "- [ ] Task checkbox-2: Beta task.",
            "beta details",
            "- [ ] Task checkbox-3: Gamma task.",
            "gamma details",
        ]
    )
    selected = parse_markdown_tasks(markdown)[1]

    excerpt = focused_task_board_excerpt(markdown, selected, limit=110)

    assert "[task-board excerpt centered on daemon-selected task]" in excerpt
    assert "Task checkbox-2: Beta task." in excerpt
    assert "Task checkbox-1: Alpha task." not in excerpt
    assert truncate_text("abcdef", limit=3) == "abc\n\n[truncated]\n"
    assert truncate_text("abcdef", limit=10) == "abcdef"


def test_relevant_file_context_helpers_are_reusable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    logic_dir = repo / "src" / "lib" / "logic"
    logic_dir.mkdir(parents=True)
    (logic_dir / "runtime.ts").write_text("export const runtime = true;\n", encoding="utf-8")
    (logic_dir / "runtime.test.ts").write_text("test('runtime', () => true);\n", encoding="utf-8")
    (logic_dir / "unrelated.ts").write_text("export const unrelated = true;\n", encoding="utf-8")
    docs = repo / "docs"
    docs.mkdir()
    (docs / "runtime.md").write_text("runtime docs\n", encoding="utf-8")
    task = Task(index=1, title="Port runtime feature with TypeScript parity", status="needed", checkbox_id=1)
    tracked_files = "\n".join(
        [
            "src/lib/logic/unrelated.ts",
            "src/lib/logic/runtime.test.ts",
            "src/lib/logic/runtime.ts",
            "docs/runtime.md",
        ]
    )

    tokens = task_title_tokens(task)
    selected = select_relevant_context_paths(
        tracked_files,
        tokens,
        allowed_prefixes=("src/lib/logic/",),
        suffixes=(".ts",),
        max_files=2,
    )
    rendered = render_relevant_file_context(
        repo_root=repo,
        tracked_files=tracked_files,
        task_or_title=task,
        allowed_prefixes=("src/lib/logic/",),
        suffixes=(".ts",),
        max_files=2,
    )

    assert tokens == ["runtime", "feature"]
    assert rank_relevant_context_file("src/lib/logic/runtime.test.ts", tokens) > rank_relevant_context_file(
        "src/lib/logic/unrelated.ts",
        tokens,
    )
    assert selected == ["src/lib/logic/runtime.ts", "src/lib/logic/runtime.test.ts"]
    assert "### src/lib/logic/runtime.test.ts" in rendered
    assert "docs/runtime.md" not in rendered
    assert render_relevant_file_context(repo_root=repo, tracked_files=tracked_files, task_or_title=None) == (
        "[No selected task tokens available.]"
    )


def test_typescript_diagnostic_context_helpers_are_reusable() -> None:
    edits = [
        {
            "path": "src/lib/logic/feature.ts",
            "content": "\n".join(
                [
                    "export const before = true;",
                    "export const value = ;",
                    "export const after = true;",
                ]
            )
            + "\n",
        }
    ]
    edits_by_path = file_edits_by_path(edits)
    diagnostic = "tmp/work/src/lib/logic/feature.ts(2,22): error TS1005: Expression expected."

    rendered = render_typescript_diagnostic_context(
        diagnostic,
        edits_by_path,
        radius=1,
    )

    assert match_diagnostic_edit_path("tmp/work/src/lib/logic/feature.ts", edits_by_path) == (
        "src/lib/logic/feature.ts"
    )
    assert "src/lib/logic/feature.ts:2:22 TS1005: Expression expected." in rendered
    assert "> 2: export const value = ;" in rendered
    assert "  1: export const before = true;" in rendered
    assert render_file_edit_diagnostic_context(errors=[diagnostic], files=edits, radius=1) == rendered


def test_file_replacement_retry_prompt_helper_is_reusable() -> None:
    prompt = build_file_replacement_retry_prompt(
        "Original prompt",
        "summary=bad\nerrors=no files",
        attempt=2,
        attempts=3,
        correction_lines=(
            "- Return JSON.",
            "- Use files.",
        ),
    )

    assert "Original prompt" in prompt
    assert "Previous proposal attempt 1 of 3" in prompt
    assert "summary=bad\nerrors=no files" in prompt
    assert "Critical correction for attempt 2:" in prompt
    assert "- Return JSON.\n- Use files." in prompt


def test_artifact_failure_classifier_handles_provider_parse_and_quality_failures() -> None:
    assert (
        classify_artifact_failure_kind(
            {
                "errors": ["403 Forbidden <html><body>challenge</body></html>"],
                "validation_results": [],
            }
        )
        == "provider_http_403"
    )
    assert classify_artifact_failure_kind({"errors": ["call timed out"]}) == "timeout"
    assert classify_artifact_failure_kind({"errors": ["LLM response did not contain JSON"]}) == "parse"
    assert (
        classify_artifact_failure_kind(
            {"failure_kind": "validation", "validation_results": [{"stderr": "error TS2314"}]},
            quality_detector=lambda text: "TS2314" in text,
            quality_failure_kind="typescript_quality",
        )
        == "typescript_quality"
    )
    assert classify_artifact_failure_kind({"failure_kind": "preflight", "errors": ["ignored"]}) == "preflight"
    assert classify_artifact_failure_kind({"validation_results": [{"stderr": "error TS1005"}]}) == "validation"
    assert classify_artifact_failure_kind({}) == "invalid_no_change"


def test_proposal_feedback_renderer_is_reusable() -> None:
    rendered = render_proposal_feedback(
        summary="Rejected proposal",
        failure_kind="preflight",
        errors=["first", "second", "third", "fourth"],
        diagnostic_context="src/example.ts:1:1 TS1005",
        diagnostic_label="typescript_diagnostic_context",
        raw_response="abcdef",
        max_errors=3,
        raw_response_limit=4,
    )

    assert rendered == "\n".join(
        [
            "summary=Rejected proposal",
            "failure_kind=preflight",
            "errors=first; second; third",
            "typescript_diagnostic_context=src/example.ts:1:1 TS1005",
            "response_prefix=abcd",
        ]
    )
    assert "fourth" not in rendered


def test_task_result_failure_context_helper_is_reusable() -> None:
    rows = [
        (
            {"valid": False},
            {
                "target_task": "Task checkbox-1: Port runtime feature",
                "summary": "old failure",
                "failure_kind": "validation",
                "errors": ["old"],
            },
        ),
        (
            {"valid": False},
            {
                "target_task": "Task checkbox-2: Other task",
                "summary": "ignored",
                "failure_kind": "validation",
            },
        ),
        (
            {"valid": False},
            {
                "target_task": "Task checkbox-1: Port runtime feature",
                "summary": "new failure",
                "failure_kind": "typescript_quality",
                "errors": ["bad syntax", "bad type"],
                "validation_results": [
                    {
                        "command": ["npx", "tsc", "--noEmit"],
                        "returncode": 2,
                        "stdout": "compiler stdout",
                        "stderr": "compiler stderr",
                    }
                ],
            },
        ),
    ]

    context = format_task_result_failure_context(rows, "Task checkbox-1: Port runtime feature", limit=2)

    assert "Summary: old failure" in context
    assert "Summary: new failure" in context
    assert "Other task" not in context
    assert "npx tsc --noEmit" in context
    assert "compiler stderr" in context


def test_plan_task_selection_and_backlog_helpers_are_reusable() -> None:
    markdown = "\n".join(
        [
            "- [x] Complete task",
            "- [!] Blocked alpha",
            "- [!] Blocked beta",
            "- [ ] Open `runtime` task",
        ]
    )
    tasks = extract_plan_tasks(markdown)
    rows = [
        (
            {"valid": False},
            {
                "target_task": "Task checkbox-2: Blocked alpha",
                "failure_kind": "validation",
                "summary": "bad alpha",
                "errors": ["first", "second", "third"],
            },
        )
    ]

    def failure_summary(_rows, task_label):
        if "Blocked alpha" in task_label:
            return {
                "total_since_success": 3,
                "by_kind_since_success": {"validation": 3},
                "latest_failure": {
                    "failure_kind": "validation",
                    "summary": "bad alpha",
                    "errors": ["first", "second", "third"],
                },
            }
        return {"total_since_success": 1, "by_kind_since_success": {"parse": 1}, "latest_failure": {}}

    backlog = build_blocked_task_backlog(
        tasks,
        rows,
        failure_summary_fn=failure_summary,
        failure_budget_exhausted_fn=lambda task, _rows: task.task_id == "checkbox-2",
        limit=4,
    )
    backlog_markdown = blocked_task_backlog_markdown(backlog)
    selected_blocked = select_blocked_plan_task(
        tasks,
        rows,
        strategy="fewest-failures",
        failure_budget_exhausted_fn=lambda task, _rows: task.task_id == "checkbox-2",
        recent_total_failure_count_fn=lambda _rows, label: 5 if "alpha" in label.lower() else 1,
        last_task_attempt_index_fn=lambda _rows, _label: 0,
    )

    assert markdown_task_label(tasks[3]) == "Task checkbox-4: Open 'runtime' task"
    assert first_open_plan_task(tasks) == tasks[3]
    assert select_next_plan_task(tasks) == tasks[3]
    assert plan_task_from_latest_result(
        tasks,
        {"artifact": {"target_task": "Task checkbox-4: Open 'runtime' task"}},
    ) == tasks[3]
    assert backlog[0]["failure_budget_exhausted"] is True
    assert "failure kinds: `{\"validation\": 3}`" in backlog_markdown
    assert "latest errors: first; second" in backlog_markdown
    assert selected_blocked == tasks[2]
    assert select_next_plan_task(
        tasks[:3],
        revisit_blocked=True,
        blocked_selector=lambda blocked_tasks: select_blocked_plan_task(blocked_tasks, rows),
    ) == tasks[1]


def test_path_policy_validates_allowlist_and_private_artifacts() -> None:
    policy = PathPolicy(
        allowed_write_prefixes=("todo/", "docs/PLAN.md"),
        disallowed_write_prefixes=("todo/private-source/",),
        private_write_path_fragments=("storage-state",),
        private_write_path_tokens=frozenset({"session"}),
        runtime_only_change_paths=frozenset({"todo/runtime/status.json"}),
        visible_source_prefixes=("todo/",),
    )

    assert policy.validate_write_path("todo/source.py") == []
    assert "outside example daemon allowlist" in policy.validate_write_path(
        "elsewhere/source.py",
        daemon_label="example daemon",
    )[0]
    assert any(
        "private/session artifacts" in error
        for error in policy.validate_write_path("todo/auth/session.json")
    )
    assert any(
        "disallowed example daemon write target" in error
        for error in policy.validate_write_path(
            "todo/private-source/x.py",
            daemon_label="example daemon",
        )
    )
    assert policy.has_visible_source_change(["todo/source.py"])
    assert not policy.has_visible_source_change(["todo/runtime/status.json"])


def test_proposal_preflight_policy_helpers_are_reusable() -> None:
    policy = ProposalPreflightPolicy(
        forbidden_snippets=("from 'vitest'",),
        forbidden_snippet_message="forbidden {snippet}",
        prefer_file_edits=True,
        file_edit_required_prefixes=("src/runtime/",),
        file_edit_required_message="runtime patch needs files",
        implementation_required_prefixes=("src/runtime/",),
        implementation_excluded_prefixes=("src/runtime/parity/",),
        non_implementation_task_keywords=("docs", "fixture"),
        implementation_required_message="implementation needs runtime",
        fixture_task_keywords=("fixture",),
        fixture_test_prefixes=("src/runtime/",),
        fixture_test_suffixes=(".test.ts",),
        fixture_test_required_message="fixture needs test",
    )

    implementation_task = Task(index=1, title="Port runtime feature", status="needed", checkbox_id=1)
    fixture_task = Task(index=2, title="Add fixture parity capture", status="needed", checkbox_id=2)

    assert task_title_contains_any(fixture_task, ("fixture",))
    assert paths_include_required_change(
        ["src/runtime/parity/data.json", "src/runtime/feature.ts"],
        prefixes=("src/runtime/",),
        excluded_prefixes=("src/runtime/parity/",),
    )
    assert preflight_proposal_payload(
        patch="diff --git a/src/runtime/feature.ts b/src/runtime/feature.ts\nfrom 'vitest'",
        files=[],
        paths=["src/runtime/feature.ts"],
        selected_task=implementation_task,
        proposal_transport="llm_router",
        default_transport="llm_router",
        policy=policy,
    ) == ["forbidden from 'vitest'", "runtime patch needs files"]
    assert preflight_proposal_payload(
        patch="",
        files=[{"path": "docs/note.md", "content": "ok"}],
        paths=["docs/note.md"],
        selected_task=implementation_task,
        policy=policy,
    ) == ["implementation needs runtime"]
    assert preflight_proposal_payload(
        patch="",
        files=[{"path": "src/runtime/parity/fixtures.json", "content": "[]"}],
        paths=["src/runtime/parity/fixtures.json"],
        selected_task=fixture_task,
        policy=policy,
    ) == ["fixture needs test"]
    assert preflight_proposal_payload(
        patch="diff --git a/src/runtime/feature.ts b/src/runtime/feature.ts\n",
        files=[],
        paths=["src/runtime/feature.ts"],
        selected_task=implementation_task,
        proposal_transport="worktree",
        default_transport="llm_router",
        policy=policy,
    ) == []


def test_parse_json_proposal_accepts_plain_json_and_filters_invalid_files() -> None:
    proposal = parse_json_proposal(
        json.dumps(
            {
                "summary": "Reusable proposal",
                "impact": "Exercises shared parser",
                "files": [
                    {"path": "todo/source.py", "content": "VALUE = 1\n"},
                    {"path": "todo/ignored.py"},
                    "not-a-file",
                ],
                "validation_commands": [["python3", "-m", "compileall", "todo"]],
            }
        )
    )

    assert proposal.summary == "Reusable proposal"
    assert proposal.files == [{"path": "todo/source.py", "content": "VALUE = 1\n"}]
    assert proposal.validation_commands == [["python3", "-m", "compileall", "todo"]]


def test_parse_file_replacement_response_accepts_json_file_edits_and_patch_fallback() -> None:
    patch = "diff --git a/todo/source.py b/todo/source.py\n--- a/todo/source.py\n+++ b/todo/source.py\n"
    response = parse_file_replacement_response(
        json.dumps(
            {
                "summary": "Reusable response",
                "impact": "Exercises shared file replacement parser",
                "patch": patch,
                "tasks": ["Task 1", 2],
                "files": [
                    {"path": "todo/source.py", "content": "VALUE = 2\n"},
                    {"path": "todo/ignored.py"},
                ],
                "validation_commands": [["python3", "-m", "py_compile", "todo/source.py"]],
            }
        )
    )
    diff_response = parse_file_replacement_response("```diff\ndiff --git a/a b/a\n--- a/a\n+++ b/a\n```\n")

    assert response.summary == "Reusable response"
    assert response.impact == "Exercises shared file replacement parser"
    assert response.patch == patch
    assert response.tasks == ["Task 1", "2"]
    assert response.files == [{"path": "todo/source.py", "content": "VALUE = 2\n"}]
    assert response.validation_commands == [["python3", "-m", "py_compile", "todo/source.py"]]
    assert "diff --git" in diff_response.patch
    assert diff_response.summary == "Patch extracted from fenced diff block."


def test_parse_file_replacement_response_marks_empty_codex_event_stream() -> None:
    response = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "example"}),
            json.dumps({"type": "turn.started"}),
        ]
    )

    proposal = parse_file_replacement_response(response)

    assert proposal.failure_kind == "codex_empty_event_stream"
    assert proposal.errors == ["Codex returned JSONL startup events without an assistant proposal."]


def test_build_file_replacement_validation_repair_prompt_renders_failed_results_and_rules() -> None:
    proposal = Proposal(
        summary="Broken candidate",
        target_task="Task checkbox-9: Repair the candidate.",
        changed_files=["todo/source.py"],
        validation_results=[
            CommandResult(("python3", "-m", "py_compile", "todo/source.py"), 1, "", "SyntaxError: bad"),
            CommandResult(("python3", "-m", "pytest", "todo"), 0, "ok", ""),
        ],
    )

    prompt = build_file_replacement_validation_repair_prompt(
        proposal,
        subject="synthetic daemon candidate",
        repair_rules=("Edit only files under todo/.", "Return complete-file replacements."),
        response_shape='{"summary":"short","files":[{"path":"todo/...","content":"..."}]}',
    )

    assert "synthetic daemon candidate" in prompt
    assert "Task checkbox-9: Repair the candidate." in prompt
    assert "- todo/source.py" in prompt
    assert "SyntaxError: bad" in prompt
    assert "py_compile" in prompt
    assert "pytest" not in prompt
    assert "- Edit only files under todo/." in prompt
    assert '{"summary":"short"' in prompt


def test_attempt_file_replacement_validation_repair_updates_failed_candidate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    (repo / "todo").mkdir(parents=True)
    (worktree / "todo").mkdir(parents=True)
    (repo / "todo" / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    (worktree / "todo" / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    config = SyntheticDaemonConfig(repo_root=repo)
    proposal = Proposal(
        summary="Broken candidate",
        target_task="Task checkbox-9: Repair candidate",
        files=[{"path": "todo/source.py", "content": "VALUE = ;\n"}],
        changed_files=["todo/source.py"],
        validation_results=[CommandResult(("validate",), 1, "", "SyntaxError")],
        errors=["Validation failed"],
    )

    repaired, changed, diff_text = attempt_file_replacement_validation_repair(
        proposal,
        config,
        worktree,
        enabled=True,
        max_attempts=1,
        build_prompt=lambda _proposal, _config: "repair this",
        call_repair_model=lambda prompt, _config: json.dumps(
            {
                "summary": "Fixed candidate",
                "impact": "Validation should pass.",
                "files": [{"path": "todo/source.py", "content": "VALUE = 2\n"}],
            }
        ),
        parse_repair=parse_json_proposal,
        validate_write_path=lambda _path: [],
        syntax_preflight=lambda _worktree, _changed, _config: ([], [], ""),
        run_validation=lambda _config, commands: [CommandResult(commands[0], 0, "ok", "")],
        validation_commands_for_proposal=lambda _proposal, _config: (("validate",),),
    )

    assert repaired is True
    assert changed == ["todo/source.py"]
    assert proposal.summary == "Fixed candidate"
    assert proposal.impact == "Validation should pass."
    assert proposal.errors == []
    assert proposal.files == [{"path": "todo/source.py", "content": "VALUE = 2\n"}]
    assert "+VALUE = 2" in diff_text


def test_normalize_file_edits_filters_invalid_entries() -> None:
    assert normalize_file_edits(
        [
            {"path": "todo/source.py", "content": "VALUE = 1\n", "extra": "ignored"},
            {"path": "todo/ignored.py"},
            {"path": 123, "content": "bad"},
            "not-a-file",
        ]
    ) == [{"path": "todo/source.py", "content": "VALUE = 1\n"}]
    assert normalize_file_edits({"path": "todo/source.py", "content": "VALUE = 1\n"}) == []


def test_normalize_validation_commands_filters_invalid_entries() -> None:
    assert normalize_string_item_lists(
        [
            ["python3", "-m", "pytest"],
            ["npm", 123],
            "pytest",
            [],
        ]
    ) == [["python3", "-m", "pytest"], []]
    assert normalize_validation_commands(
        [
            ["python3", "-m", "pytest"],
            ["npm", 123],
            "pytest",
            [],
        ]
    ) == [["python3", "-m", "pytest"], []]
    assert normalize_validation_commands({"command": ["pytest"]}) == []


def test_normalize_task_references_filters_invalid_entries() -> None:
    assert normalize_string_items(["Task A", 7, 2.5, {"title": "ignored"}, None]) == ["Task A"]
    assert normalize_string_items(
        ["Task A", 7, 2.5, {"title": "ignored"}, None],
        accepted_scalar_types=(str, int, float),
    ) == [
        "Task A",
        "7",
        "2.5",
    ]
    assert normalize_task_references(["Task A", 7, 2.5, {"title": "ignored"}, None]) == [
        "Task A",
        "7",
        "2.5",
    ]
    assert normalize_task_references("Task A") == []


def test_task_board_status_helpers_are_reusable() -> None:
    start = "<!-- synthetic-daemon-task-board:start -->"
    end = "<!-- synthetic-daemon-task-board:end -->"
    board = "\n".join(
        [
            "- [x] Task checkbox-1: Done.",
            "- [ ] Task checkbox-2: Needed.",
            "",
            "## Generated Status",
            "",
            "Last updated: stale",
            "",
            "- Latest target: `stale`",
            "",
            start,
            "## Generated Status",
            "",
            "Last updated: managed",
            end,
        ]
    )
    tasks = parse_markdown_tasks(board)

    cleaned = strip_unmanaged_generated_status_sections(
        board,
        start_marker=start,
        end_marker=end,
    )
    block = generated_status_block(
        latest={"target_task": "Task checkbox-2: Needed.", "result": "accepted", "summary": "ok"},
        tasks=tasks,
        start_marker=start,
        end_marker=end,
        now=lambda: "2026-01-01T00:00:00Z",
    )
    updated = update_generated_status_block(
        board,
        latest={"target_task": "Task checkbox-2: Needed.", "result": "accepted", "summary": "ok"},
        tasks=tasks,
        start_marker=start,
        end_marker=end,
        now=lambda: "2026-01-01T00:00:00Z",
    )

    assert count_unmanaged_generated_status_sections(board, start_marker=start, end_marker=end) == 1
    assert count_unmanaged_generated_status_sections(cleaned, start_marker=start, end_marker=end) == 0
    assert "Latest target: `stale`" not in cleaned
    assert task_status_counts(tasks) == {"needed": 1, "in_progress": 0, "complete": 1, "blocked": 0}
    assert "- Counts: `{\"blocked\": 0, \"complete\": 1, \"in_progress\": 0, \"needed\": 1}`" in block
    assert managed_status_block_pattern(start, end).search(updated)
    assert updated.count("## Generated Status") == 1
    assert "2026-01-01T00:00:00Z" in updated


def test_codex_jsonl_helpers_parse_assistant_proposals() -> None:
    response = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "example"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "```json\n{\"summary\":\"from codex\",\"files\":[]}\n```",
                            }
                        ],
                    },
                }
            ),
        ]
    )

    candidates = extract_codex_event_text_candidates(response)

    assert candidates == ["```json\n{\"summary\":\"from codex\",\"files\":[]}\n```"]
    assert extract_json(response) == {"summary": "from codex", "files": []}
    assert looks_like_empty_codex_event_stream(json.dumps({"type": "thread.started"}))
    assert not looks_like_empty_codex_event_stream(response)


def test_command_result_compaction_omits_html_and_provider_tokens() -> None:
    compacted = CommandResult(
        command=("example",),
        returncode=1,
        stdout="<html><body><script>challenge</script></body></html>",
        stderr="token __cf_chl_tk=secret",
    ).compact()

    assert "challenge" not in compacted["stdout"]
    assert "__cf_chl_tk=secret" not in compacted["stderr"]


def test_command_result_adapters_accept_objects_and_mappings() -> None:
    @dataclass(frozen=True)
    class ExternalResult:
        command: tuple[str, ...]
        returncode: int
        stdout: str = ""
        stderr: str = ""

    object_result, mapping_result, valid_mapping_result, invalid_result = command_results_from_objects(
        [
            ExternalResult(("python3", "-m", "py_compile", "todo/source.py"), 0, "ok", ""),
            {"command": ["pytest", "-q"], "returncode": "1", "stderr": "failed"},
            {"command": ["git", "status"], "returncode": None, "valid": True, "stdout": "clean"},
            {"command": "bad", "returncode": "not-int"},
        ]
    )

    assert object_result == CommandResult(
        ("python3", "-m", "py_compile", "todo/source.py"),
        0,
        "ok",
        "",
    )
    assert mapping_result == CommandResult(("pytest", "-q"), 1, "", "failed")
    assert valid_mapping_result == CommandResult(("git", "status"), 0, "clean", "")
    assert invalid_result == CommandResult((), 1, "", "")
    assert command_result_from_object(None) == CommandResult((), 1, "", "")


def test_command_runner_from_legacy_function_adapts_timeout_and_stdin(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def legacy_run_command(command, *, cwd, timeout=60, input_text=None):
        calls.append(
            {
                "command": tuple(command),
                "cwd": cwd,
                "timeout": timeout,
                "input_text": input_text,
            }
        )
        return {
            "valid": True,
            "returncode": None,
            "command": list(command),
            "stdout": input_text or "",
            "stderr": "",
        }

    run_legacy = command_runner_from_legacy_function(legacy_run_command)
    result = run_legacy(("python3", "-m", "compileall"), cwd=tmp_path, timeout_seconds=17, stdin="ok")
    ledger_path = tmp_path / "events.jsonl"
    append_jsonl(ledger_path, {"path": Path("docs/plan.md"), "ok": True})

    assert result == CommandResult(("python3", "-m", "compileall"), 0, "ok", "")
    assert json.loads(ledger_path.read_text(encoding="utf-8")) == {
        "ok": True,
        "path": "docs/plan.md",
    }
    assert calls == [
        {
            "command": ("python3", "-m", "compileall"),
            "cwd": tmp_path,
            "timeout": 17,
            "input_text": "ok",
        }
    ]


def test_shared_run_command_supports_timeout_seconds_and_stdin(tmp_path: Path) -> None:
    ok = run_command(
        ("python3", "-c", "import sys; print(sys.stdin.read().upper())"),
        cwd=tmp_path,
        timeout_seconds=5,
        stdin="ok",
    )
    timed_out = run_command(
        ("python3", "-c", "import time; time.sleep(30)"),
        cwd=tmp_path,
        timeout_seconds=1,
    )

    assert ok.ok
    assert ok.stdout.strip() == "OK"
    assert timed_out.returncode == 124
    assert "Command timed out after 1s" in timed_out.stderr


def test_thread_deadline_helper_returns_text_and_forwards_kwargs() -> None:
    def generate(prefix: str, *, suffix: str) -> str:
        return f"{prefix}-{suffix}"

    assert (
        call_with_thread_deadline(
            generate,
            "ok",
            suffix="done",
            timeout_seconds=1,
            thread_name="test-deadline-success",
        )
        == "ok-done"
    )


def test_thread_deadline_helper_reraises_worker_exception() -> None:
    class ExpectedError(RuntimeError):
        pass

    def generate() -> str:
        raise ExpectedError("worker failed")

    try:
        call_with_thread_deadline(generate, timeout_seconds=1, thread_name="test-deadline-error")
    except ExpectedError as exc:
        assert str(exc) == "worker failed"
    else:  # pragma: no cover - assertion branch.
        raise AssertionError("expected worker exception to be reraised")


def test_thread_deadline_helper_reports_timeout() -> None:
    timeouts: list[tuple[float, float, str]] = []

    def generate() -> str:
        time.sleep(0.2)
        return "late"

    def on_timeout(elapsed: float, timeout: float, thread_name: str) -> None:
        timeouts.append((elapsed, timeout, thread_name))

    def timeout_message(elapsed: float, timeout: float, thread_name: str) -> str:
        return f"{thread_name} timed out after {elapsed:.3f}s / {timeout:.3f}s"

    try:
        call_with_thread_deadline(
            generate,
            timeout_seconds=0.01,
            thread_name="test-deadline-timeout",
            on_timeout=on_timeout,
            timeout_message=timeout_message,
        )
    except TimeoutError as exc:
        assert "test-deadline-timeout timed out" in str(exc)
    else:  # pragma: no cover - assertion branch.
        raise AssertionError("expected timeout")

    assert timeouts
    assert timeouts[0][1] == 0.01
    assert timeouts[0][2] == "test-deadline-timeout"


def test_typescript_repair_helpers_are_reusable() -> None:
    damaged = "\n".join(
        [
            "const tokens: Array = [];",
            "for (let index = 0; index = tokens.length; index += 1) {",
            "  console.log(tokens[index]);",
            "}",
        ]
    )
    repaired = repair_common_typescript_text_damage(damaged)

    assert "const tokens: Array<string> = [];" in repaired
    assert "index < tokens.length" in repaired
    assert repair_common_typescript_file_edits(
        [
            {"path": "src/example.ts", "content": damaged},
            {"path": "README.md", "content": "const values: Array = [];"},
        ]
    ) == [
        {"path": "src/example.ts", "content": repaired},
        {"path": "README.md", "content": "const values: Array = [];"},
    ]
    assert obvious_typescript_text_damage("if (index  values.length) {\nconst x: Promise = y;") == [
        "line 1: missing comparison operator before .length: if (index  values.length) {",
        "line 2: bare TypeScript generic alias: const x: Promise = y;",
    ]


def test_validation_command_helpers_are_reusable(tmp_path: Path) -> None:
    default_commands = (("python3", "-c", "print('default')"),)
    trusted = Proposal(
        validation_commands=[["python3", "-c", "print('trusted')"]],
        trusted_validation_commands=True,
    )
    untrusted = Proposal(
        validation_commands=[["python3", "-c", "print('ignored')"]],
        trusted_validation_commands=False,
    )

    calls: list[tuple[str, ...]] = []

    def fake_run_command(command, *, cwd, timeout_seconds):
        calls.append(tuple(command))
        assert cwd == tmp_path
        assert timeout_seconds == 11
        return CommandResult(tuple(command), 0, "ok", "")

    results = run_validation_commands(
        repo_root=tmp_path,
        commands=validation_commands_for_proposal(trusted, default_commands),
        timeout_seconds=11,
        run_command_fn=fake_run_command,
    )

    assert validation_commands_for_proposal(trusted, default_commands) == (
        ("python3", "-c", "print('trusted')"),
    )
    assert validation_commands_for_proposal(untrusted, default_commands) == default_commands
    assert calls == [("python3", "-c", "print('trusted')")]
    assert results[0].ok


def test_llm_router_invocation_runs_isolated_child_with_prefixed_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SYNTH_LLM_BACKEND", raising=False)
    package = tmp_path / "ipfs_datasets_py"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "llm_router.py").write_text(
        "\n".join(
            [
                "import json",
                "",
                "def generate_text(prompt, model_name, provider, allow_local_fallback, timeout, max_new_tokens, temperature):",
                "    return json.dumps({",
                "        'prompt': prompt,",
                "        'model_name': model_name,",
                "        'provider': provider,",
                "        'allow_local_fallback': allow_local_fallback,",
                "        'timeout': timeout,",
                "        'max_new_tokens': max_new_tokens,",
                "        'temperature': temperature,",
                "    })",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = json.loads(
        call_llm_router(
            "hello",
            LlmRouterInvocation(
                repo_root=tmp_path,
                model_name="example-model",
                provider="example-provider",
                allow_local_fallback=True,
                timeout_seconds=7,
                max_new_tokens=321,
                max_prompt_chars=1000,
                temperature=0.2,
                backend_env_name="SYNTH_LLM_BACKEND",
                env_prefix="SYNTH_LLM",
                prompt_file_prefix="synthetic-llm-prompt-",
            ),
        )
    )

    assert payload == {
        "prompt": "hello",
        "model_name": "example-model",
        "provider": "example-provider",
        "allow_local_fallback": True,
        "timeout": 7,
        "max_new_tokens": 321,
        "temperature": 0.2,
    }


def test_llm_router_invocation_passes_optional_trace_kwargs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SYNTH_LLM_BACKEND", raising=False)
    package = tmp_path / "ipfs_datasets_py"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "llm_router.py").write_text(
        "\n".join(
            [
                "import json",
                "",
                "def generate_text(prompt, model_name, provider, allow_local_fallback, timeout, max_new_tokens, temperature, trace=False, trace_dir=None):",
                "    return json.dumps({'trace': trace, 'trace_dir': trace_dir})",
                "",
                "def get_last_generation_trace():",
                "    return {'effective_provider_name': 'codex_cli'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = json.loads(
        call_llm_router(
            "hello",
            LlmRouterInvocation(
                repo_root=tmp_path,
                timeout_seconds=7,
                max_prompt_chars=1000,
                backend_env_name="SYNTH_LLM_BACKEND",
                env_prefix="SYNTH_LLM",
                trace=True,
                trace_dir=tmp_path / "traces",
            ),
        )
    )

    assert payload == {"trace": True, "trace_dir": str(tmp_path / "traces")}


def test_daemon_history_helpers_are_reusable(tmp_path: Path) -> None:
    log = tmp_path / "daemon.jsonl"
    rows = [
        {"results": [{"valid": True, "artifact": {"target_task": "Task `A`", "summary": "done"}}]},
        {
            "results": [
                {
                    "valid": False,
                    "artifact": {
                        "target_task": "Task A",
                        "summary": "first",
                        "failure_kind": "preflight",
                        "errors": ["bad path"],
                    },
                }
            ]
        },
        {
            "results": [
                {
                    "valid": False,
                    "artifact": {
                        "target_task": "Task `A`",
                        "summary": "second",
                        "failure_kind": "validation",
                        "errors": ["bad type"],
                    },
                }
            ]
        },
    ]
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    parsed = read_daemon_results(log)
    summary = task_failure_summary(parsed, "Task A")

    assert len(parsed) == 3
    assert recent_failure_count(parsed, "Task A", "validation") == 1
    assert recent_failure_count(parsed, "Task A", "preflight") == 0
    assert recent_total_failure_count(parsed, "Task A") == 2
    assert current_task_failure_counts(parsed, "Task A") == {
        "total_since_success": 2,
        "by_kind_since_success": {"validation": 1, "preflight": 1},
    }
    assert rounds_since_last_valid(parsed) == 2
    assert last_task_attempt_index(parsed, "Task A") == 2
    assert summary["latest_failure"]["failure_kind"] == "validation"
    assert summary["latest_failure"]["errors"] == ["bad type"]


def test_proposal_record_history_helpers_read_runner_jsonl_shapes(tmp_path: Path) -> None:
    log = tmp_path / "runner.jsonl"
    rows = [
        {"proposal": {"target_task": "Task A", "failure_kind": "llm", "errors": ["first"]}},
        {"stage": "before_validation", "diagnostic": {"target_task": "Task A", "failure_kind": "parse"}},
        {
            "proposal": {
                "target_task": "Task B",
                "applied": True,
                "validation_passed": True,
                "errors": [],
            }
        },
        {"proposal": {"target_task": "Task A", "failure_kind": "llm", "errors": ["second"]}},
    ]
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\nnot-json\n", encoding="utf-8")

    proposals = read_daemon_proposal_records(log)
    with_diagnostics = read_daemon_proposal_records(log, include_diagnostics=True)
    failures = recent_proposal_failures(with_diagnostics, "Task A", limit=3)

    assert [row.get("failure_kind") for row in proposals] == ["llm", None, "llm"]
    assert [row.get("failure_kind") for row in with_diagnostics] == ["llm", "parse", None, "llm"]
    assert with_diagnostics[1]["_diagnostic_stage"] == "before_validation"
    assert [row["failure_kind"] for row in failures] == ["llm", "parse", "llm"]
    assert should_use_compact_prompt_for_failures(failures)
    assert not should_use_compact_prompt_for_failures([{"failure_kind": "validation"}])


def test_daemon_diagnostic_failure_loop_helpers_are_reusable() -> None:
    rows = [
        (
            {"valid": True},
            {"target_task": "Task A", "failure_kind": "", "errors": []},
        ),
        (
            {"valid": False},
            {
                "target_task": "Task `A`",
                "failure_kind": "quality",
                "errors": ["src/example.ts(1,1): error TS2339: Property 'foo' does not exist."],
                "validation_results": [{"stdout": "", "stderr": "error TS2339: Property 'bar' does not exist."}],
            },
        ),
        (
            {"valid": False},
            {
                "target_task": "Task `A`",
                "failure_kind": "quality",
                "errors": ["src/example.ts(2,1): error TS2339: Property 'baz' does not exist."],
                "validation_results": [],
            },
        ),
        (
            {"valid": False},
            {
                "target_task": "Task B",
                "failure_kind": "parse",
                "errors": ["bad json"],
                "changed_files": ["todo/output.py"],
            },
        ),
    ]

    quality_counts = quality_failure_counts(
        rows,
        classify_failure_kind=lambda artifact: str(artifact.get("failure_kind") or ""),
        quality_failure_kind="quality",
    )
    rollback_counts = rollback_failure_counts(
        rows,
        classify_failure_kind=lambda artifact: str(artifact.get("failure_kind") or ""),
        rollback_failure_kinds=frozenset({"quality", "parse"}),
    )

    assert has_diagnostic_codes(artifact_validation_text(rows[1][1]), frozenset({"TS2339"}))
    assert diagnostic_signatures(artifact_validation_text(rows[1][1])) == [
        "TS2339:Property '<symbol>' does not exist."
    ]
    assert quality_counts["total"] == 2
    assert quality_counts["consecutive"] == 0
    assert quality_counts["by_task"] == {"Task `A`": 2}
    assert quality_counts["top_signature_count"] == 2
    assert rollback_counts["total"] == 2
    assert rollback_counts["consecutive"] == 0
    assert rollback_counts["by_kind"] == {"quality": 2}
    assert recent_rollback_failure_count(
        rows[:-1],
        "Task A",
        classify_failure_kind=lambda artifact: str(artifact.get("failure_kind") or ""),
        rollback_failure_kinds=frozenset({"quality"}),
    ) == 2


def test_proposal_retry_policy_helpers_are_reusable() -> None:
    retryable = Proposal(
        failure_kind="validation",
        errors=["provider timed out while generating candidate"],
    )
    empty_llm = Proposal(failure_kind="llm")
    source_only = Proposal(
        failure_kind="no_visible_source_change",
        files=[{"path": "todo/status.json", "content": "{}\n"}],
    )
    record = {"failure_kind": "llm", "errors": ["llm_router child exited with code -15:"]}

    assert is_retryable_proposal_failure(retryable)
    assert proposal_error_text(retryable) == "provider timed out while generating candidate"
    assert should_skip_validation_for_empty_proposal(empty_llm)
    assert not should_skip_validation_for_empty_proposal(source_only)
    assert block_threshold_for_failure_kind(
        "syntax_preflight",
        default_threshold=3,
        capped_failure_kinds=frozenset({"syntax_preflight"}),
        capped_threshold=2,
    ) == 2
    assert proposal_block_threshold(
        source_only,
        default_threshold=3,
        exact_thresholds={"no_visible_source_change": 1},
    ) == 1
    assert prompt_limit_for_mode(
        max_prompt_chars=60000,
        max_compact_prompt_chars=3600,
        compact_prompt=True,
    ) == 3600
    assert prompt_limit_for_mode(
        max_prompt_chars=60000,
        max_compact_prompt_chars=3600,
        compact_prompt=False,
    ) == 60000
    assert proposal_record_has_failure_markers(
        record,
        failure_kind="llm",
        markers=frozenset({"code -15"}),
    )
    assert count_proposal_records_with_failure_markers(
        [record, {"failure_kind": "llm", "errors": ["other"]}],
        failure_kind="llm",
        markers=frozenset({"code -15"}),
    ) == 1
    assert count_recent_proposal_failures(
        [{"failure_kind": "llm"}, {"failure_kind": "validation"}],
        failure_kinds=frozenset({"llm"}),
    ) == 1
    context = format_recent_failure_context(
        [
            {
                "failure_kind": "validation",
                "summary": "bad candidate",
                "errors": ["SyntaxError: invalid syntax"],
                "validation_results": [
                    {
                        "command": ["python3", "-m", "compileall", "todo"],
                        "returncode": 1,
                        "stdout": "",
                        "stderr": "compile failed",
                    }
                ],
            }
        ],
        guidance=lambda failures: ["retry guidance"] if failures else [],
    )
    assert "Failure 1: kind=validation" in context
    assert "python3 -m compileall todo: compile failed" in context
    assert "retry guidance" in context
    status_artifact = compact_status_artifact(
        {
            "summary": "large proposal",
            "target_task": "Task checkbox-1: Port feature",
            "impact": "updates runtime",
            "changed_files": ["todo/source.py"],
            "errors": ["one", "two", "three"],
            "validation_passed": True,
        },
        classify_failure_kind=lambda _artifact: "validation",
        max_errors=2,
    )
    assert status_artifact == {
        "summary": "large proposal",
        "target_task": "Task checkbox-1: Port feature",
        "impact": "updates runtime",
        "valid_changed_files": ["todo/source.py"],
        "errors": ["one", "two"],
        "failure_kind": "validation",
        "validation_passed": True,
    }


def test_status_payload_helpers_preserve_active_state_for_heartbeats(tmp_path: Path) -> None:
    snapshot = ActiveStatusSnapshot(state="initializing", started_at="t0")

    selected = advance_active_status_snapshot(
        snapshot,
        state="selected_task",
        now="t1",
        target_task="Task checkbox-1: Port feature",
    )
    same = advance_active_status_snapshot(
        selected,
        state="selected_task",
        now="t2",
        target_task="Task checkbox-1: Port feature",
    )
    changed = advance_active_status_snapshot(
        same,
        state="applying_files",
        now="t3",
    )
    heartbeat_snapshot = advance_active_status_snapshot(changed, state="heartbeat", now="t4")

    assert selected.started_at == "t1"
    assert same.started_at == "t1"
    assert changed.started_at == "t3"
    assert heartbeat_snapshot == changed
    assert status_started_at(
        {"state": "llm_call_started", "state_started_at": "old"},
        state="llm_call_started",
        now="new",
    ) == "old"
    assert status_started_at(
        {"state": "llm_call_started", "state_started_at": "old"},
        state="llm_call_completed",
        now="new",
    ) == "new"
    assert status_key_started_at(
        {"phase_key": "3|requesting_worktree_edit", "phase_started_at": "p-old"},
        current_key="3|requesting_worktree_edit",
        now="p-new",
    ) == "p-old"
    assert status_key_started_at(
        {"phase_key": "3|requesting_worktree_edit", "phase_started_at": "p-old"},
        current_key="3|running_tests",
        now="p-new",
    ) == "p-new"
    assert build_status_phase_key(
        "retrying_worktree_edit",
        cycle_index=7,
        details={"proposal_attempt": 2, "retry_reason": "patch validation failed"},
    ) == "7|retrying_worktree_edit|attempt=2|retry=patch validation failed"

    payload = build_active_status_payload(
        state="heartbeat",
        snapshot=changed,
        now="t5",
        pid=123,
        extra={"active_state": "custom-heartbeat"},
    )

    assert payload["pid"] == 123
    assert payload["updated_at"] == "t5"
    assert payload["state"] == "heartbeat"
    assert payload["active_state"] == "custom-heartbeat"
    assert payload["active_state_started_at"] == "t3"
    assert payload["active_target_task"] == "Task checkbox-1: Port feature"

    heartbeat = build_heartbeat_status_payload(
        {"state": "llm_call_started", "state_started_at": "s1", "model_name": "gpt-5.5"},
        now="h1",
        timestamp_key="timestamp",
        heartbeat_interval_seconds=15.0,
    )

    assert heartbeat["timestamp"] == "h1"
    assert heartbeat["updated_at"] == "h1"
    assert heartbeat["heartbeat_at"] == "h1"
    assert heartbeat["state"] == "heartbeat"
    assert heartbeat["active_state"] == "llm_call_started"
    assert heartbeat["active_state_started_at"] == "s1"
    assert heartbeat["heartbeat_interval_seconds"] == 15.0
    assert heartbeat["model_name"] == "gpt-5.5"

    ready = build_ready_after_supervisor_repair_status(
        created_at="r1",
        previous_status={
            "active_state": "calling_llm",
            "active_target_task": "Task checkbox-1: Port feature.",
        },
        repair_state="ready_after_supervisor_repair",
        supervisor_action="reconcile_dead_worker_and_restart",
        supervisor_reason="worker exited mid-cycle",
        reset_task_labels=("Port feature.",),
    )

    assert ready["updated_at"] == "r1"
    assert ready["state"] == "ready_after_supervisor_repair"
    assert ready["active_state"] == "ready_after_supervisor_repair"
    assert ready["active_target_task"] == ""
    assert ready["previous_state"] == "calling_llm"
    assert ready["previous_target_task"] == "Task checkbox-1: Port feature."
    assert ready["reset_task_labels"] == ["Port feature."]

    output = tmp_path / "nested" / "status.json"
    write_status_json(
        output,
        {"created_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)},
        trailing_newline=True,
    )

    assert output.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "created_at": "2026-01-02 03:04:05+00:00"
    }


def test_failure_block_and_exception_diagnostics_are_reusable() -> None:
    decision = first_failure_block_decision(
        (
            FailureBlockRule(
                failure_kind="syntax_preflight",
                count=1,
                threshold=2,
                summary="not yet",
                result="keep_retrying",
            ),
            FailureBlockRule(
                failure_kind="llm_termination",
                count=2,
                threshold=2,
                summary="stop before LLM",
                result="llm_blocked",
            ),
        )
    )

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        diagnostic = exception_diagnostic(exc, limit=2000)

    assert decision is not None
    assert decision.failure_kind == "llm_termination"
    assert decision.summary == "stop before LLM"
    assert decision.result == "llm_blocked"
    assert "RuntimeError: boom" in diagnostic


def test_git_parsing_helpers_are_reusable() -> None:
    status = "\n".join(
        [
            " M ipfs_datasets_py/logic/deontic/parser.py",
            "R  old.py -> new.py",
            "?? tests/unit_tests/logic/deontic/test_parser.py",
        ]
    )
    diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/parser.py b/ipfs_datasets_py/logic/deontic/parser.py",
            "--- a/ipfs_datasets_py/logic/deontic/parser.py",
            "+++ b/ipfs_datasets_py/logic/deontic/parser.py",
            "@@ -1,2 +1,1 @@",
            "-old",
            "-line",
            "+new",
            "diff --git a/tests/unit_tests/logic/deontic/test_parser.py b/tests/unit_tests/logic/deontic/test_parser.py",
            "--- a/tests/unit_tests/logic/deontic/test_parser.py",
            "+++ b/tests/unit_tests/logic/deontic/test_parser.py",
            "@@ -1 +1,2 @@",
            " test",
            "+extra",
        ]
    )

    stats = unified_diff_stats(
        diff,
        test_file_prefixes=("tests/unit_tests/logic/deontic/",),
        production_file_prefixes=("ipfs_datasets_py/logic/deontic/",),
    )

    assert paths_from_git_status_porcelain(status) == [
        "ipfs_datasets_py/logic/deontic/parser.py",
        "new.py",
        "tests/unit_tests/logic/deontic/test_parser.py",
    ]
    assert untracked_paths_from_git_status_porcelain(status) == [
        "tests/unit_tests/logic/deontic/test_parser.py"
    ]
    assert paths_from_unified_diff(diff) == [
        "ipfs_datasets_py/logic/deontic/parser.py",
        "tests/unit_tests/logic/deontic/test_parser.py",
    ]
    assert unique_normalized_paths(["todo\\one.py", "todo/one.py", "", "todo/two.py"]) == [
        "todo/one.py",
        "todo/two.py",
    ]
    assert paths_from_file_edits(
        [
            {"path": "todo\\one.py", "content": "one"},
            {"path": "todo/two.py", "content": "two"},
            {"content": "ignored"},
        ]
    ) == ["todo/one.py", "todo/two.py"]
    assert paths_from_patch_and_file_edits(
        diff,
        [{"path": "todo\\one.py", "content": "one"}],
    ) == [
        "todo/one.py",
        "ipfs_datasets_py/logic/deontic/parser.py",
        "tests/unit_tests/logic/deontic/test_parser.py",
    ]
    assert stats["files_changed"] == 2
    assert stats["insertions"] == 2
    assert stats["deletions"] == 2
    assert stats["deletion_heavy_files"] == ["ipfs_datasets_py/logic/deontic/parser.py"]
    assert stats["production_deletion_heavy_files"] == ["ipfs_datasets_py/logic/deontic/parser.py"]
    assert stats["test_deletion_heavy_files"] == []


def test_auto_commit_helpers_are_reusable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    logic_file = repo / "src" / "lib" / "logic" / "feature.ts"
    notes_file = repo / "notes.txt"
    logic_file.parent.mkdir(parents=True)
    logic_file.write_text("export const feature = 'old';\n", encoding="utf-8")
    notes_file.write_text("old notes\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    logic_file.write_text("export const feature = 'new';\n", encoding="utf-8")
    notes_file.write_text("dirty notes\n", encoding="utf-8")
    statuses: list[tuple[str, dict[str, object]]] = []
    config = AutoCommitConfig(
        repo_root=repo,
        enabled=True,
        dry_run=False,
        required_branch="main",
        allowed_prefixes=("src/lib/logic/",),
        command_timeout_seconds=30,
        subject_prefix="chore(todo-test):",
        user_name="Todo Test",
        user_email="todo-test@example.invalid",
    )

    result = auto_commit_paths(
        config,
        ["src/lib/logic/feature.ts", "notes.txt", "../outside.ts"],
        reason="validated daemon round",
        target_task="Task checkbox-1: Port feature",
        summary="Runtime feature works",
        write_status_fn=lambda state, **details: statuses.append((state, details)),
    )

    assert slugify("Runtime feature works!") == "runtime-feature-works"
    assert repo_relative_pathspec(logic_file, repo_root=repo) == "src/lib/logic/feature.ts"
    assert safe_auto_commit_pathspecs(
        ["./src/lib/logic/feature.ts", "notes.txt", "../outside.ts", "src/lib/logic/feature.ts"],
        allowed_prefixes=("src/lib/logic/",),
    ) == ["src/lib/logic/feature.ts"]
    assert build_auto_commit_subject(
        summary="Runtime feature works",
        subject_prefix="chore(todo-test):",
    ) == "chore(todo-test): runtime feature works"
    assert result["committed"] is True
    assert result["changed_files"] == ["src/lib/logic/feature.ts"]
    assert [state for state, _details in statuses] == ["auto_commit_started", "auto_commit_completed"]
    assert statuses[0][1]["auto_commit_paths"] == ["src/lib/logic/feature.ts"]

    logic_status = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/lib/logic"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    notes_status = subprocess.run(
        ["git", "status", "--porcelain", "--", "notes.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert logic_status.stdout == ""
    assert notes_status.stdout.startswith(" M notes.txt")
    assert subject.stdout.strip() == "chore(todo-test): runtime feature works"


def test_artifact_sidecar_and_ledger_helpers_are_reusable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    artifact_dir = repo / ".daemon" / "accepted-work"
    diff_text = "diff --git a/todo/source.py b/todo/source.py\n+VALUE = 2\n"
    proposal = Proposal(
        summary="Runtime feature works",
        impact="Reusable artifact evidence.",
        target_task="Task checkbox-1: Port feature",
        files=[{"path": "todo/source.py", "content": "VALUE = 2\n"}],
        changed_files=["todo/source.py"],
        validation_results=[CommandResult(("pytest", "-q"), 0, "ok", "")],
        promotion_verified=True,
    )

    base = timestamped_artifact_base(
        artifact_dir,
        summary=proposal.summary,
        fallback="accepted-work",
        reason="accepted",
        now=lambda: "2026-05-05T01:02:03Z",
    )
    paths = write_work_sidecars(
        base=base,
        manifest=accepted_work_manifest(proposal, transport="ephemeral_worktree"),
        workspace=accepted_work_workspace_payload(proposal, transport="ephemeral_worktree"),
        diff_text=diff_text,
        changed_files=proposal.changed_files,
    )
    ledger_entry = build_accepted_work_ledger_entry(
        repo_root=repo,
        target_task=proposal.target_task,
        summary=proposal.summary,
        impact=proposal.impact,
        changed_files=proposal.changed_files,
        transport="ephemeral_worktree",
        artifacts=paths,
        validation_results=proposal.validation_results,
        diff_text=diff_text,
        promotion_verified=proposal.promotion_verified,
        created_at="2026-05-05T01:02:03Z",
    )
    ledger_path = append_jsonl_ledger(
        artifact_dir,
        ledger_entry,
        filename=DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
    )
    scoped_entry = build_scoped_accepted_work_ledger_entry(
        repo_root=repo,
        accepted_dir=artifact_dir,
        target_task=proposal.target_task,
        summary="Ledger only runtime feature",
        impact=proposal.impact,
        changed_files=proposal.changed_files,
        transport="ephemeral_worktree",
        artifacts=None,
        validation_results=proposal.validation_results,
        diff_text=diff_text,
        promotion_verified=proposal.promotion_verified,
        created_at="2026-05-05T01:02:04Z",
    )
    proposal_entry = build_proposal_accepted_work_ledger_entry(
        repo_root=repo,
        accepted_dir=artifact_dir,
        proposal=proposal,
        transport="ephemeral_worktree",
        artifacts=None,
        diff_text=diff_text,
        created_at="2026-05-05T01:02:05Z",
    )
    scoped_ledger_path = append_accepted_work_ledger(artifact_dir, scoped_entry)
    evidence_manifest = accepted_work_evidence_manifest(
        timestamp="20260505T010203Z",
        target_task=proposal.target_task,
        summary=proposal.summary,
        impact=proposal.impact,
        changed_files=proposal.changed_files,
        validation_results=proposal.validation_results,
        diff_stat="todo/source.py | 1 +",
        diff_available=True,
    )
    markdown_entry = accepted_work_markdown_entry(
        timestamp="2026-05-05 01:02:03 UTC",
        target_task=proposal.target_task,
        summary=proposal.summary,
        impact=proposal.impact,
        changed_files=proposal.changed_files,
        evidence_paths=[as_repo_path(paths.manifest, repo)],
        validation_results=proposal.validation_results,
    )
    markdown_log = artifact_dir / "accepted.md"
    append_accepted_work_markdown_log(
        markdown_log,
        markdown_entry,
        title="Example Daemon Accepted Work",
        description="Example accepted-work evidence.",
    )
    commands: list[tuple[str, ...]] = []

    def fake_run_command(command, *, cwd, timeout_seconds):
        commands.append(tuple(command))
        assert cwd == repo
        assert timeout_seconds == 17
        stdout = "todo/source.py | 1 +\n" if "--stat" in command else diff_text
        return CommandResult(tuple(command), 0, stdout, "")

    legacy_root = artifact_dir / "legacy"
    legacy_paths = write_accepted_work_evidence_artifacts(
        root=legacy_root,
        repo_root=repo,
        artifact={
            "target_task": proposal.target_task,
            "summary": proposal.summary,
            "impact": proposal.impact,
            "validation_results": [result.compact() for result in proposal.validation_results],
        },
        changed_files=proposal.changed_files,
        run_command_fn=fake_run_command,
        command_timeout_seconds=17,
        now=lambda: "2026-05-05T01:02:03Z",
    )
    legacy_base = legacy_root / "20260505T010203Z-runtime-feature-works"
    legacy_sidecars = AcceptedWorkEvidencePaths(
        manifest=Path(str(legacy_base) + ".json"),
        diff=Path(str(legacy_base) + ".diff"),
        stat=Path(str(legacy_base) + ".stat.txt"),
    )
    failed_manifest = failed_work_manifest(
        Proposal(
            summary="Broken edit",
            target_task="Task checkbox-2: Broken",
            errors=["Traceback line\nwith details"],
            validation_results=[CommandResult(("pytest",), 1, "", "failed")],
        ),
        reason="validation",
        transport="ephemeral_worktree",
    )
    failed_workspace = failed_work_workspace_payload(
        Proposal(summary="Broken edit", changed_files=["todo/source.py"]),
        reason="validation",
        transport="ephemeral_worktree",
    )

    assert isinstance(paths, WorkSidecarPaths)
    assert base.name == "20260505T010203Z-accepted-runtime-feature-works"
    assert sidecar_paths(base) == paths
    assert slugify_artifact_name("Runtime Feature Works!", fallback="work") == "runtime-feature-works"
    assert artifact_string_items(["todo/source.py", "", Path("docs/note.md"), 7]) == [
        "todo/source.py",
        "docs/note.md",
    ]
    assert paths.manifest.exists()
    assert paths.workspace.exists()
    assert paths.diff.read_text(encoding="utf-8") == diff_text
    assert paths.stat.read_text(encoding="utf-8") == "todo/source.py\n"
    assert json.loads(paths.manifest.read_text(encoding="utf-8"))["promotion_verified"] is True
    assert json.loads(paths.workspace.read_text(encoding="utf-8"))["promoted"] is True
    assert ledger_entry["schema_version"] == ACCEPTED_WORK_LEDGER_SCHEMA_VERSION
    assert ledger_entry["validation_passed"] is True
    assert ledger_entry["artifacts"]["manifest"] == as_repo_path(paths.manifest, repo)
    assert ledger_entry["diff"]["line_count"] == len(diff_text.splitlines())
    assert ledger_path.name == DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME
    assert scoped_ledger_path == ledger_path
    ledger_rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert ledger_rows[0]["summary"] == proposal.summary
    assert ledger_rows[1]["artifacts"]["mode"] == "ledger_only"
    assert ledger_rows[1]["artifacts"]["ledger"] == ".daemon/accepted-work/accepted-work.jsonl"
    assert proposal_entry["summary"] == proposal.summary
    assert proposal_entry["target_task"] == proposal.target_task
    assert proposal_entry["promotion"]["verified"] is True
    assert proposal_entry["validation_results"] == [{"command": ["pytest", "-q"], "returncode": 0}]
    assert compact_validation_result({"command": "bad", "returncode": "not-int"}) == {
        "command": [],
        "returncode": 1,
    }
    assert compact_validation_results([proposal.validation_results[0], {"command": "bad"}]) == [
        {"command": ["pytest", "-q"], "returncode": 0},
        {"command": [], "returncode": 0},
    ]
    assert evidence_manifest["validation"] == [{"command": ["pytest", "-q"], "returncode": 0}]
    assert evidence_manifest["diff_available"] is True
    assert validation_command_summaries([proposal.validation_results[0], "ignored"]) == [
        "`pytest -q` -> `0`",
    ]
    assert "# Example Daemon Accepted Work" in markdown_log.read_text(encoding="utf-8")
    assert "`todo/source.py`" in markdown_log.read_text(encoding="utf-8")
    assert "- Validation: `pytest -q` -> `0`" in markdown_log.read_text(encoding="utf-8")
    assert commands == [
        ("git", "diff", "--", "todo/source.py"),
        ("git", "diff", "--stat", "--", "todo/source.py"),
    ]
    assert legacy_paths == [
        as_repo_path(legacy_sidecars.manifest, repo),
        as_repo_path(legacy_sidecars.diff, repo),
        as_repo_path(legacy_sidecars.stat, repo),
    ]
    assert legacy_sidecars.diff.read_text(encoding="utf-8") == diff_text
    assert legacy_sidecars.stat.read_text(encoding="utf-8") == "todo/source.py | 1 +\n"
    assert json.loads(legacy_sidecars.manifest.read_text(encoding="utf-8"))["diff_available"] is True
    assert failed_manifest["reason"] == "validation"
    assert failed_manifest["validation_results"][0]["returncode"] == 1
    assert failed_workspace["reason"] == "validation"
    write_json(artifact_dir / "extra.json", {"ok": True})
    assert json.loads((artifact_dir / "extra.json").read_text(encoding="utf-8")) == {"ok": True}


def test_proposal_work_persistence_helpers_write_ledgers_and_sidecars(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    accepted_dir = repo / ".daemon" / "accepted-work"
    failed_dir = repo / ".daemon" / "failed-work"
    diff_text = "diff --git a/todo/source.py b/todo/source.py\n+VALUE = 2\n"
    proposal = Proposal(
        summary="Persist proposal work",
        impact="Reusable accepted/failed persistence.",
        target_task="Task checkbox-4: Persist work.",
        files=[{"path": "todo/source.py", "content": "VALUE = 2\n"}],
        changed_files=["todo/source.py"],
        validation_results=[CommandResult(("pytest", "-q"), 0, "ok", "")],
        promotion_verified=True,
    )

    accepted = persist_proposal_accepted_work(
        repo_root=repo,
        accepted_dir=accepted_dir,
        proposal=proposal,
        diff_text=diff_text,
        transport="ephemeral_worktree",
        write_sidecars_enabled=True,
    )
    ledger_only = persist_proposal_accepted_work(
        repo_root=repo,
        accepted_dir=Path(".daemon/accepted-work"),
        proposal=proposal,
        diff_text=diff_text,
        transport="direct",
        write_sidecars_enabled=False,
    )
    failed = persist_proposal_failed_work(
        failed_dir=Path(".daemon/failed-work"),
        proposal=Proposal(
            summary="Persist failed work",
            target_task=proposal.target_task,
            changed_files=["todo/source.py"],
            validation_results=[CommandResult(("pytest", "-q"), 1, "", "failed")],
            errors=["validation failed"],
        ),
        diff_text=diff_text,
        reason="validation",
        transport="ephemeral_worktree",
        repo_root=repo,
    )

    assert isinstance(accepted, AcceptedWorkPersistenceResult)
    assert resolve_artifact_directory(Path(".daemon/accepted-work"), repo_root=repo) == accepted_dir
    assert accepted.artifacts is not None
    assert accepted.ledger_path == accepted_dir / DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME
    assert accepted.ledger_entry["artifacts"]["mode"] == "sidecars"
    assert accepted.artifacts.diff.read_text(encoding="utf-8") == diff_text
    assert ledger_only.artifacts is None
    assert ledger_only.ledger_entry["artifacts"]["mode"] == "ledger_only"
    ledger_rows = [json.loads(line) for line in accepted.ledger_path.read_text(encoding="utf-8").splitlines()]
    assert [row["transport"] for row in ledger_rows] == ["ephemeral_worktree", "direct"]
    assert failed.manifest.exists()
    assert json.loads(failed.manifest.read_text(encoding="utf-8"))["reason"] == "validation"
    assert json.loads(failed.workspace.read_text(encoding="utf-8"))["promoted"] is False
    assert failed.diff.read_text(encoding="utf-8") == diff_text


def test_deterministic_fallback_helpers_are_reusable(tmp_path: Path) -> None:
    rules = (("processor-suite integration", "processor_suite"),)
    task = Task(
        index=1,
        title="Add processor-suite integration planning tranche 7 coverage.",
        status="needed",
        checkbox_id=42,
    )
    manifest_path = tmp_path / "progress.json"
    existing = {
        "schemaVersion": 1,
        "strategy": "deterministic",
        "records": [
            {"checkboxId": 41, "taskLabel": "Task checkbox-41: Prior"},
            {"checkboxId": "42", "taskLabel": "Task checkbox-42: Stale by string id"},
        ],
    }
    manifest_path.write_text(json.dumps(existing), encoding="utf-8")

    loaded = load_deterministic_progress_manifest(manifest_path, strategy="deterministic")
    record = build_deterministic_progress_record(
        task,
        "processor_suite",
        source_evidence_ids=("evidence:one",),
        artifact_contracts=("archive_manifest",),
        guardrails=("fixture_only",),
        blocked_actions=("submit",),
        runtime_policy={"live": False},
        now=lambda: "2026-05-05T00:00:00Z",
    )
    updated = upsert_deterministic_progress_record(
        loaded,
        task,
        record,
        now=lambda: "2026-05-05T00:01:00Z",
    )
    proposal = build_deterministic_replacement_proposal(
        selected=task,
        fallback_kind="processor_suite",
        manifest=updated,
        progress_path=Path("todo/progress.json"),
        source_files=(("todo/source.py", "VALUE = 1\n"),),
        validation_commands=(("python3", "-m", "py_compile", "todo/source.py"),),
        impact="Keeps deterministic fallback reusable.",
    )

    assert fallback_kind_for_task(task, rules) == "processor_suite"
    assert task_has_deterministic_fallback(task, rules)
    assert open_task_has_deterministic_fallback([task], rules)
    assert tranche_number_from_title(task.title) == 7
    assert record["sourceEvidenceIds"] == ["evidence:one"]
    assert record["artifactContracts"] == ["archive_manifest"]
    assert record["blockedActions"] == ["submit"]
    assert updated["updatedAt"] == "2026-05-05T00:01:00Z"
    assert [item["checkboxId"] for item in updated["records"]] == [41, 42]
    assert proposal.trusted_validation_commands is True
    assert proposal.requires_visible_source_change is True
    assert proposal.target_task == task.label
    assert proposal.files[0] == {"path": "todo/source.py", "content": "VALUE = 1\n"}
    assert proposal.files[1]["path"] == "todo/progress.json"
    assert "\"fallbackKind\": \"processor_suite\"" in proposal.files[1]["content"]


def test_plan_selection_and_blocked_backlog_helpers_are_reusable() -> None:
    tasks = [
        PlanTask("checkbox-1", "Completed task", "complete"),
        PlanTask("checkbox-2", "Blocked early", "blocked"),
        PlanTask("checkbox-3", "Open later", "needed"),
        PlanTask("checkbox-4", "Blocked later", "blocked"),
    ]
    rows = [({"artifact": {"target_task": tasks[1].label}}, {"failure_kind": "validation"})]

    def failure_summary(_rows, label):
        return {
            "total_since_success": 2 if label == tasks[1].label else 1,
            "by_kind_since_success": {"validation": 2},
            "latest_failure": {"failure_kind": "validation", "summary": "failed", "errors": ["bad"]},
        }

    backlog = build_blocked_task_backlog(
        tasks,
        rows,
        failure_summary_fn=failure_summary,
        failure_budget_exhausted_fn=lambda task, _rows: task.task_id == "checkbox-2",
        limit=3,
    )
    markdown = blocked_task_backlog_markdown(backlog)
    selected_blocked = select_blocked_plan_task(
        tasks,
        rows,
        strategy="fewest-failures",
        failure_budget_exhausted_fn=lambda task, _rows: task.task_id == "checkbox-2",
        recent_total_failure_count_fn=lambda _rows, label: 2 if "Blocked early" in label else 1,
        last_task_attempt_index_fn=lambda _rows, label: 1 if "Blocked early" in label else 0,
    )

    assert markdown_task_label(tasks[1]) == tasks[1].label
    assert plan_task_from_latest_result(tasks, {"artifact": {"target_task": tasks[1].label}}) == tasks[1]
    assert plan_task_from_latest_result(tasks, {"artifact": {"target_task": "Task checkbox-4: old title"}}) == tasks[3]
    assert first_open_plan_task(tasks) == tasks[2]
    assert select_next_plan_task(tasks) == tasks[2]
    assert select_next_plan_task(tasks[:2], revisit_blocked=True, blocked_selector=lambda _tasks: tasks[1]) == tasks[1]
    assert selected_blocked == tasks[3]
    assert backlog[0]["failure_budget_exhausted"] is True
    assert "`Task checkbox-2: Blocked early`" in markdown
    assert "failure kinds" in markdown


def test_worktree_owner_and_cleanup_helpers_are_reusable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    worktree_root = repo / ".daemon" / "worktrees"
    cycle = worktree_root / "cycle_01_20260101T000000000000Z_12345"
    repair = worktree_root / "repair_01_20260101T000000000000Z_12345"
    for index, path in enumerate((cycle, repair), start=1):
        path.mkdir(parents=True)
        owner_path = path / ".todo_owner.json"
        write_worktree_owner_file(
            owner_path,
            schema="synthetic.todo_owner",
            repo_root=repo,
            attempt=index,
            extra={"created_at_epoch": 1},
        )
        assert read_json_object(owner_path)["attempt"] == index

    calls: list[tuple[str, ...]] = []

    def fake_run_command(command, *, cwd, timeout_seconds, stdin=None):
        calls.append(tuple(command))
        if tuple(command[:3]) == ("git", "worktree", "list"):
            return CommandResult(tuple(command), 0, "", "")
        return CommandResult(tuple(command), 0, "", "")

    result = cleanup_stale_daemon_worktrees(
        repo_root=repo,
        worktree_root=worktree_root,
        stale_after_seconds=10,
        owner_filename=".todo_owner.json",
        run_command_fn=fake_run_command,
        owner_alive=lambda _pid, _repo, _worktree: False,
        now_epoch=100,
    )

    assert result["valid"] is True
    assert {Path(item["path"]).name for item in result["removed"]} == {cycle.name, repair.name}
    assert not cycle.exists()
    assert not repair.exists()
    assert owner_pid_from_worktree(Path("cycle_01_20260101T000000000000Z_54321"), {}) == 54321
    assert calls.count(("git", "worktree", "prune", "--expire", "now")) == 2
    assert ("git", "worktree", "list", "--porcelain") in calls


def test_managed_git_worktree_captures_lifecycle_trace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = repo / ".daemon" / "worktrees" / "cycle_01"
    calls: list[tuple[str, ...]] = []
    owner_paths: list[Path] = []

    def fake_run_command(command, *, cwd, timeout_seconds, stdin=None):
        command = tuple(command)
        calls.append(command)
        if command[:3] == ("git", "worktree", "add"):
            Path(command[-2]).mkdir(parents=True, exist_ok=True)
        return CommandResult(command, 0, "", "")

    with managed_git_worktree(
        repo_root=repo,
        worktree_path=worktree,
        metadata_rel=".todo_metadata.json",
        owner_rel=".todo_owner.json",
        trace_context={"transport": "synthetic_worktree", "attempt": 2},
        run_command_fn=fake_run_command,
        owner_writer=lambda owner_path: owner_paths.append(owner_path),
    ) as session:
        assert session.ready is True
        assert session.path == worktree
        assert session.raw_trace["transport"] == "synthetic_worktree"
        assert session.raw_trace["metadata_path"] == ".todo_metadata.json"
        assert session.raw_trace["owner_path"] == ".todo_owner.json"
        assert session.raw_trace["worktree_add"]["returncode"] == 0

    assert owner_paths == [worktree / ".todo_owner.json"]
    assert ("git", "worktree", "add", "--detach", str(worktree), "HEAD") in calls
    assert ("git", "worktree", "remove", "--force", str(worktree)) in calls
    assert ("git", "worktree", "prune", "--expire", "now") in calls
    assert session.raw_trace["worktree_remove"]["returncode"] == 0


def test_validation_worktree_materializes_promotes_and_cleans_up(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "todo").mkdir()
    (repo / "todo" / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "PLAN.md").write_text("Synthetic plan\n", encoding="utf-8")
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    external = repo / "external" / "metadata"
    external.mkdir(parents=True)
    (external / "record.txt").write_text("metadata\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    assert repo_relative_copy_paths(
        repo,
        (
            Path("todo"),
            repo / "docs" / "PLAN.md",
            outside,
            Path(),
        ),
    ) == (Path("todo"), Path("docs/PLAN.md"))

    spec = build_validation_workspace_spec(
        repo_root=repo,
        worktree_dir=Path(".daemon/worktrees"),
        marker_name="example-worktree.json",
        copy_paths=(Path("todo"), repo / "docs" / "PLAN.md", outside, Path()),
        root_files=("package.json",),
        external_reference_paths=(Path("external/metadata"),),
        stale_seconds=0,
    )
    proposal = Proposal(files=[{"path": "todo/source.py", "content": "VALUE = 2\n"}])

    with temporary_validation_worktree(spec) as worktree:
        assert (worktree / "example-worktree.json").exists()
        assert (worktree / "todo" / "source.py").read_text(encoding="utf-8") == "VALUE = 1\n"
        assert (worktree / "docs" / "PLAN.md").exists()
        assert (worktree / "package.json").exists()
        assert (worktree / "external" / "metadata" / "record.txt").exists()

        changed = materialize_proposal_files(proposal, worktree)
        diff = proposal_diff_from_worktree(repo, worktree, changed)

        assert changed == ["todo/source.py"]
        assert "+VALUE = 2" in diff
        promote_worktree_files(repo, worktree, changed)
        assert verify_promoted_worktree_files(repo, worktree, changed) == []

    assert not any((repo / ".daemon" / "worktrees").iterdir())


def test_dataclass_worktree_config_copies_config_with_repo_root_override(tmp_path: Path) -> None:
    @dataclass(frozen=True)
    class CustomRootConfig:
        project_root: Path
        apply: bool = True

    config = SyntheticDaemonConfig(
        repo_root=tmp_path / "repo",
        status_file=Path("custom/status.json"),
        apply=True,
    )
    worktree = tmp_path / "worktree"

    scoped = dataclass_worktree_config(config, worktree, apply=False, interval_seconds=1.5)
    custom = dataclass_worktree_config(
        CustomRootConfig(project_root=tmp_path / "project"),
        worktree,
        repo_root_field="project_root",
        apply=False,
    )

    assert scoped.repo_root == worktree
    assert scoped.status_file == Path("custom/status.json")
    assert scoped.apply is False
    assert scoped.interval_seconds == 1.5
    assert config.repo_root == tmp_path / "repo"
    assert config.apply is True
    assert custom.project_root == worktree
    assert custom.apply is False
    try:
        dataclass_worktree_config({"repo_root": tmp_path}, worktree)
    except TypeError as exc:
        assert "dataclass config instance" in str(exc)
    else:
        raise AssertionError("expected dataclass_worktree_config to reject non-dataclass configs")


def test_config_repo_root_file_replacement_helpers_use_daemon_config_root(tmp_path: Path) -> None:
    @dataclass(frozen=True)
    class CustomRootConfig:
        project_root: Path

    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo.mkdir()
    worktree.mkdir()
    (repo / "todo").mkdir()
    (worktree / "todo").mkdir()
    (repo / "todo" / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    (worktree / "todo" / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
    changed = ["todo/source.py"]

    config = SyntheticDaemonConfig(repo_root=repo)
    diff = config_proposal_diff_from_worktree(config, worktree, changed)

    assert config_repo_root(config) == repo
    assert config_repo_root(CustomRootConfig(project_root=repo), repo_root_field="project_root") == repo
    assert "+VALUE = 2" in diff
    config_promote_worktree_files(config, worktree, changed)
    assert config_verify_promoted_worktree_files(config, worktree, changed) == []
    assert (repo / "todo" / "source.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_supervisor_heartbeat_and_worker_watchdog_helpers_are_reusable() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    current = {
        "heartbeat_at": (now - timedelta(seconds=5)).isoformat(),
        "heartbeat_pid": 999999999,
        "phase": "requesting_worktree_edit",
        "phase_started_at": (now - timedelta(seconds=45)).isoformat(),
    }

    heartbeat = heartbeat_snapshot(current, stale_after_seconds=30, now=now)
    stale_heartbeat = heartbeat_snapshot(
        {**current, "heartbeat_at": (now - timedelta(seconds=31)).isoformat()},
        stale_after_seconds=30,
        now=now,
    )
    worker_status = worktree_phase_worker_status(
        current,
        daemon_pid=999999999,
        threshold_seconds=30,
        now=now,
    )

    assert heartbeat.age_seconds == 5
    assert heartbeat.fresh is True
    assert heartbeat.stale is False
    assert heartbeat.pid_alive is False
    assert stale_heartbeat.stale is True
    assert worker_status["required"] is True
    assert worker_status["phase"] == "requesting_worktree_edit"
    assert worker_status["phase_age_seconds"] == 45
    assert worker_status["active_worker_count"] == 0
    assert worker_status["stalled_without_active_worker"] is True


def test_supervisor_maintenance_snapshot_tracks_fresh_agentic_repairs() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    supervisor = {
        "status": "agentic_maintenance_started",
        "updated_at": (now - timedelta(seconds=120)).isoformat(),
        "last_agentic_maintenance_status": "running",
        "last_agentic_maintenance_reason": "stuck_phase:calling_llm",
        "agentic_timeout_seconds": 30,
        "agentic_stuck_maintenance_timeout_seconds": 180,
    }

    snapshot = supervisor_maintenance_snapshot(
        supervisor,
        now=now,
        supervisor_alive=True,
    )
    stale = supervisor_maintenance_snapshot(
        {
            **supervisor,
            "updated_at": (now - timedelta(seconds=250)).isoformat(),
        },
        now=now,
        supervisor_alive=True,
    )
    inactive = supervisor_maintenance_snapshot(
        supervisor,
        now=now,
        supervisor_alive=False,
    )

    assert snapshot.active is True
    assert snapshot.fresh is True
    assert snapshot.timeout_seconds == 180
    assert snapshot.age_seconds == 120
    assert snapshot.rounded_age_seconds == 120
    assert stale.fresh is False
    assert stale.age_seconds == 250
    assert inactive.active is True
    assert inactive.fresh is False
    assert inactive.age_seconds is None


def test_supervisor_maintenance_snapshot_supports_legacy_suffix_statuses() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    snapshot = supervisor_maintenance_snapshot(
        {
            "status": "custom_repair_started",
            "active_agentic_maintenance_started_at": (now - timedelta(seconds=50)).isoformat(),
            "active_agentic_maintenance_timeout_seconds": 75,
            "last_agentic_maintenance_status": "still_running",
        },
        now=now,
        supervisor_alive=True,
        active_statuses=(),
        active_status_suffixes=("_started",),
        running_statuses=(),
        running_status_suffixes=("running",),
    )

    assert snapshot.active is True
    assert snapshot.fresh is True
    assert snapshot.timeout_seconds == 75
    assert snapshot.rounded_age_seconds == 50


def test_first_present_preserves_false_and_zero_status_values() -> None:
    assert first_present(None, "", "fallback") == "fallback"
    assert first_present(None, False, "fallback") is False
    assert first_present("", 0, "fallback") == 0
    assert first_present(None, "") is None


def test_supervisor_status_payload_builder_is_reusable(tmp_path: Path) -> None:
    spec = ManagedDaemonSpec(
        name="synthetic",
        schema="synthetic.todo_daemon",
        repo_root=tmp_path,
        daemon_dir=Path(".daemon"),
        runner=("python3", "-m", "synthetic.daemon"),
        status_path=Path(".daemon/status.json"),
        progress_path=Path(".daemon/progress.json"),
        supervisor_status_path=Path(".daemon/supervisor.json"),
        supervisor_pid_path=Path(".daemon/supervisor.pid"),
        child_pid_path=Path(".daemon/child.pid"),
        supervisor_out_path=Path(".daemon/supervisor.out"),
        ensure_status_path=Path(".daemon/ensure.json"),
        ensure_check_path=Path(".daemon/ensure-check.json"),
        supervisor_lock_path=Path(".daemon/supervisor.lock"),
    )

    payload = build_supervisor_status_payload(
        spec,
        status="running",
        run_id="run-1",
        log_path=".daemon/run.log",
        daemon_pid=123,
        restart_count=2,
        last_exit_code=None,
        supervisor_pid=456,
        static_fields={"watchdog_stale_after_seconds": 90},
        extra={"model_name": "gpt-5.5"},
    )

    assert payload["schema"] == "synthetic.todo_daemon.supervisor"
    assert payload["status"] == "running"
    assert payload["supervisor_pid"] == 456
    assert payload["daemon_pid"] == 123
    assert payload["restart_count"] == 2
    assert payload["current_status_path"] == ".daemon/status.json"
    assert payload["progress_path"] == ".daemon/progress.json"
    assert payload["child_pid_path"] == ".daemon/child.pid"
    assert payload["supervisor_lock_path"] == ".daemon/supervisor.lock"
    assert payload["watchdog_stale_after_seconds"] == 90
    assert payload["model_name"] == "gpt-5.5"


def test_restart_wrapper_command_builder_is_reusable() -> None:
    assert quoted_env_assignments(
        {"MODEL_NAME": "gpt 5.5", "PROVIDER": "llm_router"},
        ("MODEL_NAME", "MISSING", "PROVIDER"),
    ) == "MODEL_NAME='gpt 5.5' PROVIDER=llm_router"

    command = build_restart_loop_command(
        ("bash", "scripts/run_daemon.sh"),
        env={"MODEL_NAME": "gpt-5.5", "PROVIDER": "llm_router"},
        env_keys=("MODEL_NAME", "PROVIDER"),
        restart_delay_seconds=11,
        restart_message="legal-parser supervisor exited with code",
    )

    assert command.startswith(
        "while true; do MODEL_NAME=gpt-5.5 PROVIDER=llm_router bash scripts/run_daemon.sh; "
    )
    assert "legal-parser supervisor exited with code" in command
    assert "wrapper restarting in %ss" in command
    assert "sleep 11; done" in command


def test_restarting_wrapper_liveness_helper_supports_tmux_and_pid_modes(tmp_path, monkeypatch) -> None:
    from ipfs_datasets_py.optimizers.todo_daemon import wrapper as wrapper_module

    monkeypatch.setattr(wrapper_module, "tmux_available", lambda: True)
    monkeypatch.setattr(wrapper_module, "tmux_has_session", lambda name: name == "todo-daemon")

    missing_pid_path = tmp_path / "wrapper.pid"
    assert restarting_wrapper_alive(
        launch_mode="tmux",
        tmux_session_name="todo-daemon",
        pid_path=missing_pid_path,
        command_fragments=("run_todo_daemon.sh",),
    )
    assert not restarting_wrapper_alive(
        launch_mode="nohup_loop",
        tmux_session_name="todo-daemon",
        pid_path=missing_pid_path,
        command_fragments=("run_todo_daemon.sh",),
    )


def test_lifecycle_wrapper_renderer_matches_legacy_shell_shape() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cases = default_lifecycle_wrapper_script_specs()

    assert all(isinstance(item, LifecycleWrapperScriptSpec) for item in cases)
    assert len(cases) == 6

    for file_spec in cases:
        spec = file_spec.wrapper
        script_path = repo_root / file_spec.path
        script = script_path.read_text(encoding="utf-8")
        payload = lifecycle_wrapper_payload(spec)
        script_payload = lifecycle_wrapper_script_payload(file_spec)
        for line in lifecycle_wrapper_core_lines(spec):
            assert line in script
        assert missing_lifecycle_wrapper_core_lines(script, spec) == ()
        assert lifecycle_wrapper_matches_rendered(script, spec)
        assert payload["daemon"] == spec.daemon
        assert payload["command"] == spec.command
        assert script_payload["path"] == file_spec.path
        assert script_payload["daemon"] == spec.daemon

    rendered = render_lifecycle_wrapper(
        LifecycleWrapperSpec(
            daemon="example",
            command="check",
            repo_root_ancestor="../..",
            pythonpath_expr="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}",
            compatibility_markers=("legacy marker",),
        )
    )

    assert rendered.startswith("#!/usr/bin/env bash\nset -uo pipefail\n")
    assert "# legacy marker" in rendered
    assert "exec python3 -m ipfs_datasets_py.optimizers.todo_daemon example check \"$@\"" in rendered


def test_supervisor_child_runtime_helpers_are_reusable(tmp_path: Path) -> None:
    run_id = supervisor_run_id(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    command = (
        "python3",
        "-c",
        "import os; print('child-ok:' + os.environ.get('EXAMPLE_DAEMON', ''))",
    )
    spec = SupervisedChildSpec(
        repo_root=tmp_path,
        command=command,
        log_path=supervised_log_path(Path(".daemon"), prefix="synthetic_child", run_id=run_id),
        child_pid_path=Path(".daemon/child.pid"),
        latest_log_path=Path(".daemon/latest.log"),
        env={"EXAMPLE_DAEMON": "todo"},
    )

    child = launch_supervised_child(spec)
    rc = wait_for_child_exit(child)

    assert run_id == "20260102T030405Z"
    assert build_python_module_command("synthetic.daemon", ("--once",), python_executable="py") == (
        "py",
        "-u",
        "-m",
        "synthetic.daemon",
        "--once",
    )
    assert RestartPolicy(restart_backoff_seconds=30, fast_restart_backoff_seconds=2).delay_for_status(
        "no_change"
    ) == 2
    assert RestartPolicy(restart_backoff_seconds=30, fast_restart_backoff_seconds=2).delay_for_status(
        "validation_failed"
    ) == 30
    assert rc == 0
    assert child.child_pid_path.read_text(encoding="utf-8").strip() == str(child.pid)
    assert child.latest_log_path is not None
    assert child.latest_log_path.is_symlink()
    assert child.latest_log_path.read_text(encoding="utf-8").strip() == "child-ok:todo"
    assert clear_child_pid_file(child) is True
    assert not child.child_pid_path.exists()


def test_supervisor_loop_cli_config_helpers_are_reusable(tmp_path: Path) -> None:
    parser = build_supervisor_loop_arg_parser(description="Synthetic supervisor.")
    args = parser.parse_args(
        [
            "--repo-root",
            str(tmp_path),
            "--name",
            "synthetic-loop",
            "--env",
            "EXAMPLE=1",
            "--max-restarts",
            "1",
            "--poll-seconds",
            "0.01",
            "--",
            "python3",
            "-c",
            "print('ok')",
        ]
    )

    config = supervisor_loop_config_from_args(args)
    payload = supervisor_loop_result_payload(
        SupervisorLoop(config).run()
    )

    assert config.spec.name == "synthetic-loop"
    assert config.command == ("python3", "-c", "print('ok')")
    assert config.poll_seconds == 0.01
    assert config.child_env == {"EXAMPLE": "1"}
    assert payload["status"] == "child_exited"
    assert payload["restart_count"] == 1
    assert payload["last_exit_code"] == 0


def test_supervisor_loop_cli_runs_supervised_child(tmp_path: Path, capsys) -> None:
    rc = run_supervisor_loop_cli(
        [
            "--repo-root",
            str(tmp_path),
            "--name",
            "synthetic-cli-loop",
            "--daemon-dir",
            ".daemon",
            "--status-path",
            ".daemon/status.json",
            "--progress-path",
            ".daemon/progress.json",
            "--supervisor-status-path",
            ".daemon/supervisor.json",
            "--supervisor-pid-path",
            ".daemon/supervisor.pid",
            "--child-pid-path",
            ".daemon/child.pid",
            "--supervisor-out-path",
            ".daemon/supervisor.out",
            "--ensure-status-path",
            ".daemon/ensure.json",
            "--ensure-check-path",
            ".daemon/ensure-check.json",
            "--supervisor-lock-path",
            ".daemon/supervisor.lock",
            "--latest-log-path",
            ".daemon/latest.log",
            "--log-prefix",
            "synthetic_cli",
            "--heartbeat-seconds",
            "0.01",
            "--watchdog-startup-grace-seconds",
            "0",
            "--max-restarts",
            "1",
            "--env",
            "EXAMPLE_DAEMON=cli",
            "--",
            "python3",
            "-c",
            "import os; print('cli:' + os.environ['EXAMPLE_DAEMON'])",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "child_exited"
    assert payload["restart_count"] == 1
    assert payload["last_exit_code"] == 0
    assert (tmp_path / ".daemon" / "latest.log").read_text(encoding="utf-8").strip() == "cli:cli"


def test_python_supervisor_loop_reuses_child_runtime_and_status(tmp_path: Path) -> None:
    spec = ManagedDaemonSpec(
        name="synthetic-loop",
        schema="synthetic.todo_daemon",
        repo_root=tmp_path,
        daemon_dir=Path(".daemon"),
        runner=("python3", "-m", "synthetic.daemon"),
        status_path=Path(".daemon/child-status.json"),
        progress_path=Path(".daemon/progress.json"),
        supervisor_status_path=Path(".daemon/supervisor.json"),
        supervisor_pid_path=Path(".daemon/supervisor.pid"),
        child_pid_path=Path(".daemon/child.pid"),
        supervisor_out_path=Path(".daemon/supervisor.out"),
        ensure_status_path=Path(".daemon/ensure.json"),
        ensure_check_path=Path(".daemon/ensure-check.json"),
        supervisor_lock_path=Path(".daemon/supervisor.lock"),
        latest_log_path=Path(".daemon/latest-child.log"),
    )
    loop = SupervisorLoop(
        SupervisorLoopConfig(
            spec=spec,
            command=("python3", "-c", "print('loop-once')"),
            log_prefix="synthetic_loop",
            heartbeat_seconds=0.01,
            watchdog_startup_grace_seconds=0.0,
            max_restarts=1,
            status_static_fields={"example_supervisor": True},
        )
    )

    result = loop.run()
    supervisor_status = json.loads((tmp_path / ".daemon" / "supervisor.json").read_text(encoding="utf-8"))

    assert result.status == "child_exited"
    assert result.restart_count == 1
    assert result.last_exit_code == 0
    assert not (tmp_path / ".daemon" / "child.pid").exists()
    assert (tmp_path / ".daemon" / "latest-child.log").read_text(encoding="utf-8").strip() == "loop-once"
    assert supervisor_status["status"] == "child_exited"
    assert supervisor_status["restart_count"] == 1
    assert supervisor_status["example_supervisor"] is True


def test_file_replacement_apply_flow_promotes_only_after_validation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "todo").mkdir()
    target = repo / "todo" / "source.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    config = SyntheticDaemonConfig(repo_root=repo)
    spec = ValidationWorkspaceSpec(
        repo_root=repo,
        worktree_dir=Path(".daemon/worktrees"),
        marker_name="example-worktree.json",
        copy_paths=(Path("todo"),),
    )
    accepted: list[tuple[str, str]] = []
    failed: list[tuple[str, str, str]] = []

    hooks = FileReplacementHooks(
        validate_write_path=lambda path: [] if path.startswith("todo/") else ["outside allowlist"],
        temporary_validation_worktree=validation_worktree_for_spec(spec),
        validation_commands_for_proposal=lambda _proposal, _config: (("synthetic-validation",),),
        run_validation=lambda _config, commands: [CommandResult(commands[0], 0, "ok", "")],
        syntax_preflight=lambda _worktree, _changed, _config: (
            [CommandResult(("synthetic-preflight",), 0, "ok", "")],
            [],
            "",
        ),
        has_visible_source_change=lambda changed: any(path.endswith(".py") for path in changed),
        attempt_validation_repair=lambda proposal, _config, _worktree: (False, proposal.changed_files, ""),
        persist_failed_work=lambda _proposal, _config, diff_text, reason, transport: failed.append(
            (reason, transport, diff_text)
        ),
        persist_accepted_work=lambda proposal, _config, _diff_text, transport: accepted.append(
            (proposal.summary, transport)
        ),
    )

    result = build_file_replacement_apply_proposal(hooks)(
        Proposal(
            summary="Accepted reusable flow",
            files=[{"path": "todo/source.py", "content": "VALUE = 2\n"}],
            requires_visible_source_change=True,
        ),
        config,
    )

    assert result.valid
    assert result.promotion_verified
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert accepted == [("Accepted reusable flow", "ephemeral_worktree")]
    assert failed == []


def test_file_replacement_apply_flow_rejects_disallowed_paths(tmp_path: Path) -> None:
    config = SyntheticDaemonConfig(repo_root=tmp_path)
    failed: list[tuple[str, str, str]] = []

    hooks = FileReplacementHooks(
        validate_write_path=lambda _path: ["outside allowlist"],
        temporary_validation_worktree=lambda _config: temporary_validation_worktree(
            ValidationWorkspaceSpec(repo_root=tmp_path, worktree_dir=Path(".daemon/worktrees"))
        ),
        validation_commands_for_proposal=lambda _proposal, _config: (),
        run_validation=lambda _config, _commands: [],
        syntax_preflight=lambda _worktree, _changed, _config: ([], [], ""),
        has_visible_source_change=lambda _changed: False,
        attempt_validation_repair=lambda proposal, _config, _worktree: (False, proposal.changed_files, ""),
        persist_failed_work=lambda _proposal, _config, diff_text, reason, transport: failed.append(
            (reason, transport, diff_text)
        ),
        persist_accepted_work=lambda _proposal, _config, _diff_text, _transport: None,
    )

    result = apply_file_replacement_proposal(
        Proposal(files=[{"path": "elsewhere/source.py", "content": "bad\n"}]),
        config,
        hooks,
    )

    assert result.failure_kind == "preflight"
    assert result.errors == ["outside allowlist"]
    assert failed == [("preflight", "direct", "")]


def test_reusable_lifecycle_cli_runs_check_ensure_and_spec(tmp_path: Path, capsys) -> None:
    def build_spec(repo_root: str | None) -> ManagedDaemonSpec:
        root = Path(repo_root) if repo_root else tmp_path
        return ManagedDaemonSpec(
            name="synthetic",
            schema="synthetic.todo_daemon",
            repo_root=root,
            daemon_dir=Path(".daemon"),
            runner=("python3", "-m", "synthetic.daemon"),
            status_path=Path(".daemon/status.json"),
            progress_path=Path(".daemon/progress.json"),
            supervisor_status_path=Path(".daemon/supervisor.json"),
            supervisor_pid_path=Path(".daemon/supervisor.pid"),
            child_pid_path=Path(".daemon/child.pid"),
            supervisor_out_path=Path(".daemon/supervisor.out"),
            ensure_status_path=Path(".daemon/ensure.json"),
            ensure_check_path=Path(".daemon/ensure-check.json"),
            task_board_path=Path("todo/board.md"),
            worktree_root=Path(".daemon/worktrees"),
            launch_env={"MODEL_NAME": "gpt-5.5"},
        )

    def check_fn(spec: ManagedDaemonSpec, *, stale_after_seconds: float):
        return {
            "alive": True,
            "name": spec.name,
            "stale_after_seconds": stale_after_seconds,
        }

    ensure_seen: dict[str, object] = {}

    def ensure_fn(spec: ManagedDaemonSpec, **kwargs):
        ensure_seen.update(kwargs)
        return {
            "status": "started",
            "check": {
                "alive": True,
                "name": spec.name,
                "restart_delay_seconds": kwargs["restart_delay_seconds"],
            },
        }

    parser = build_lifecycle_arg_parser(
        description="Manage synthetic daemon.",
        default_stale_after_seconds=90,
        default_startup_wait_seconds=7,
        default_launch_mode="nohup",
        launch_mode_choices=("nohup", "tmux"),
        restart_delay_flag="--restart-delay-seconds",
        default_restart_delay_seconds=3,
        stop_description="Stop synthetic daemon.",
        run_description="Run synthetic daemon.",
    )

    rc = run_lifecycle_cli(
        ["check", "--repo-root", str(tmp_path), "--stale-after-seconds", "12"],
        parser=parser,
        build_spec=build_spec,
        check_fn=check_fn,
    )
    check_payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert check_payload["name"] == "synthetic"
    assert check_payload["stale_after_seconds"] == 12

    rc = run_lifecycle_cli(
        ["ensure", "--repo-root", str(tmp_path), "--restart-delay-seconds", "11"],
        parser=parser,
        build_spec=build_spec,
        ensure_fn=ensure_fn,
        ensure_restart_kw="restart_delay_seconds",
    )
    ensure_payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert ensure_seen["startup_wait_seconds"] == 7
    assert ensure_seen["restart_delay_seconds"] == 11
    assert ensure_payload["restart_delay_seconds"] == 11

    rc = run_lifecycle_cli(
        ["spec", "--repo-root", str(tmp_path)],
        parser=parser,
        build_spec=build_spec,
        spec_payload_builder=lambda spec: daemon_spec_payload(spec, extra={"family": "todo"}),
    )
    spec_payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert spec_payload["family"] == "todo"
    assert spec_payload["runner"] == ["python3", "-m", "synthetic.daemon"]
    assert spec_payload["task_board_path"] == "todo/board.md"

    run_seen: list[str] = []
    rc = run_lifecycle_args(
        parser.parse_args(["run", "--", "--once", "--flag"]),
        build_spec=build_spec,
        run_fn=lambda argv: run_seen.extend(list(argv or ())) or 7,
    )

    assert rc == 7
    assert run_seen == ["--once", "--flag"]


def test_todo_daemon_registry_helpers_are_reusable() -> None:
    registrations = (
        TodoDaemonRegistration(
            name="example-daemon",
            module="example.package.daemon",
            aliases=("example_daemon", "example"),
        ),
    )

    assert canonical_daemon_names(registrations) == ("example-daemon",)
    assert daemon_alias_map(registrations) == {
        "example-daemon": "example.package.daemon",
        "example_daemon": "example.package.daemon",
        "example": "example.package.daemon",
    }
    assert dispatcher_choices(registrations, extra_commands=("list",)) == (
        "example",
        "example-daemon",
        "example_daemon",
        "list",
    )
    assert resolve_daemon_module("example", registrations) == "example.package.daemon"
    assert daemon_registry_payload(registrations) == {
        "daemons": [
            {
                "name": "example-daemon",
                "module": "example.package.daemon",
                "aliases": ["example_daemon", "example"],
            }
        ]
    }
    assert callable(load_daemon_main("logic_port"))


def test_todo_daemon_spec_env_helpers_are_reusable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    env = {
        "REPO_ROOT": str(repo),
        "EMPTY": "",
        "FLAG_TRUE": "yes",
        "FLAG_FALSE": "off",
        "INT_VALUE": "8",
        "BAD_INT": "eight",
        "FLOAT_VALUE": "2.5",
        "BAD_FLOAT": "many",
        "DAEMON_DIR": "state/.daemon",
        "STATUS_PATH": "custom/status.json",
    }
    daemon_dir = env_path("DAEMON_DIR", ".daemon", env=env)

    assert env_value("MISSING", "fallback", env=env) == "fallback"
    assert env_value("EMPTY", "fallback", env=env) == "fallback"
    assert env_value("DAEMON_DIR", ".daemon", env=env) == "state/.daemon"
    assert env_flag("FLAG_TRUE", "0", env=env) == "1"
    assert env_flag("FLAG_FALSE", "1", env=env) == "0"
    assert env_int("INT_VALUE", 1, env=env) == 8
    assert env_int("BAD_INT", 3, env=env) == 3
    assert env_int("NEGATIVE", -4, env=env, minimum=0) == 0
    assert env_float("FLOAT_VALUE", 1.0, env=env) == 2.5
    assert env_float("BAD_FLOAT", 1.5, env=env) == 1.5
    assert env_float("NEGATIVE_FLOAT", -4.0, env=env, minimum=0.0) == 0.0
    assert repo_root_from_env(env=env) == repo.resolve()
    assert repo_root_from_env(str(tmp_path / "explicit"), env=env) == (tmp_path / "explicit").resolve()
    assert daemon_dir == Path("state/.daemon")
    assert env_path_in_dir("STATUS_PATH", daemon_dir, "status.json", env=env) == Path("custom/status.json")
    assert env_path_in_dir("PROGRESS_PATH", daemon_dir, "progress.json", env=env) == Path(
        "state/.daemon/progress.json"
    )


def test_package_lifecycle_dispatcher_routes_builtin_daemons(tmp_path: Path, capsys, monkeypatch) -> None:
    for name in (
        "DAEMON_DIR",
        "STATUS_PATH",
        "PROGRESS_PATH",
        "RESULT_LOG_PATH",
        "SUPERVISOR_STATUS_PATH",
        "SUPERVISOR_PID_PATH",
        "CHILD_PID_PATH",
        "SUPERVISOR_OUT_PATH",
        "ENSURE_STATUS_PATH",
        "CHECK_LOG_PATH",
        "SUPERVISOR_LOCK_PATH",
        "LATEST_LOG_PATH",
        "TASK_BOARD_PATH",
        "WORKTREE_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)

    assert daemon_names() == ("legal-parser", "logic-port")

    rc = todo_daemon_package_main(["logic-port", "spec", "--repo-root", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["name"] == "logic-port"
    assert payload["schema"] == "ipfs_datasets_py.logic_port_daemon"
    assert payload["runner"] == ["bash", "ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh"]
    assert payload["task_board_path"] == "docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md"

    rc = todo_daemon_package_main(["list"])
    listed = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert listed["daemons"] == ["legal-parser", "logic-port"]

    rc = todo_daemon_package_main(["wrappers"])
    wrappers = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert {item["daemon"] for item in wrappers["wrappers"]} == {"legal-parser", "logic-port"}
    assert {
        item["path"] for item in wrappers["wrappers"]
    } >= {
        "scripts/ops/legal_data/check_logic_port_daemon.sh",
        "scripts/ops/legal_data/ensure_legal_parser_optimizer_daemon.sh",
    }

    import ipfs_datasets_py.optimizers.todo_daemon.legal_parser as legal_parser_lifecycle
    import ipfs_datasets_py.optimizers.todo_daemon.logic_port as logic_port_lifecycle

    runtime_calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        legal_parser_lifecycle,
        "run_legal_parser_daemon_runtime",
        lambda argv: runtime_calls.append(("legal-parser", list(argv or ()))) or 0,
    )
    monkeypatch.setattr(
        logic_port_lifecycle,
        "run_logic_port_daemon_runtime",
        lambda argv: runtime_calls.append(("logic-port", list(argv or ()))) or 0,
    )

    assert todo_daemon_package_main(["legal-parser", "run", "--", "--max-cycles", "0"]) == 0
    assert todo_daemon_package_main(["logic-port", "run", "--", "--max-iterations", "0"]) == 0
    assert runtime_calls == [
        ("legal-parser", ["--max-cycles", "0"]),
        ("logic-port", ["--max-iterations", "0"]),
    ]

    rc = todo_daemon_package_main(
        [
            "supervise",
            "--repo-root",
            str(tmp_path),
            "--daemon-dir",
            ".daemon/package-supervise",
            "--status-path",
            ".daemon/package-supervise/child-status.json",
            "--progress-path",
            ".daemon/package-supervise/progress.json",
            "--supervisor-status-path",
            ".daemon/package-supervise/supervisor.json",
            "--supervisor-pid-path",
            ".daemon/package-supervise/supervisor.pid",
            "--child-pid-path",
            ".daemon/package-supervise/child.pid",
            "--supervisor-out-path",
            ".daemon/package-supervise/supervisor.out",
            "--ensure-status-path",
            ".daemon/package-supervise/ensure.json",
            "--ensure-check-path",
            ".daemon/package-supervise/ensure-check.json",
            "--supervisor-lock-path",
            ".daemon/package-supervise/supervisor.lock",
            "--latest-log-path",
            ".daemon/package-supervise/latest.log",
            "--heartbeat-seconds",
            "0.01",
            "--max-restarts",
            "1",
            "python3",
            "-c",
            "print('package-supervise')",
        ]
    )
    supervisor_payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert supervisor_payload["status"] == "child_exited"
    assert supervisor_payload["last_exit_code"] == 0


def test_reusable_todo_daemon_module_cli_runs_hooked_daemon(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    board = repo / "todo" / "board.md"
    board.parent.mkdir(parents=True)
    board.write_text("- [ ] Task checkbox-1: Module entry task.\n", encoding="utf-8")

    def replace_task_mark(markdown: str, selected: Task, mark: str) -> str:
        return re.sub(
            r"- \[[ xX~!]\] " + re.escape(selected.label),
            f"- [{mark}] " + selected.label,
            markdown,
            count=1,
        )

    def hooks_factory(_config: TodoDaemonRuntimeConfig) -> TodoDaemonHooks:
        return TodoDaemonHooks(
            parse_tasks=parse_markdown_tasks,
            select_task=lambda tasks, _config: next(iter(tasks), None),
            replace_task_mark=replace_task_mark,
            update_generated_status=lambda markdown, latest, _tasks: markdown.rstrip()
            + f"\n\nLatest result: {latest['result']}\n",
            produce_proposal=lambda _config, _selected, _write_status: Proposal(
                summary="Accepted module task",
                files=[{"path": "todo/module-output.txt", "content": "ok\n"}],
            ),
            apply_proposal=lambda proposal, _config: Proposal(
                summary=proposal.summary,
                files=proposal.files,
                validation_results=[CommandResult(("true",), 0, "", "")],
                applied=True,
                dry_run=proposal.dry_run,
                target_task=proposal.target_task,
            ),
            run_validation=lambda _config, _proposal: [CommandResult(("true",), 0, "", "")],
            should_skip_validation=lambda _proposal: False,
            is_retryable_failure=lambda _proposal: False,
            failure_block_threshold=lambda _proposal, _config: 1,
            failure_count_for_block=lambda _config, _label: 0,
            should_sleep_between_cycles=lambda _markdown, _config: False,
            exception_diagnostic=lambda exc: str(exc),
        )

    parser = build_todo_runner_arg_parser(description="Run synthetic todo module.")
    rc = run_todo_daemon_cli(
        [
            "--repo-root",
            str(repo),
            "--task-board",
            "todo/board.md",
            "--status-file",
            "todo/status.json",
            "--progress-file",
            "todo/progress.json",
            "--result-log",
            "todo/results.jsonl",
        ],
        parser=parser,
        hooks_factory=hooks_factory,
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["iterations"] == 1
    assert payload["valid"] is True
    assert payload["latest"]["summary"] == "Accepted module task"
    assert "- [x] Task checkbox-1: Module entry task." in board.read_text(encoding="utf-8")
    assert json.loads((repo / "todo" / "status.json").read_text(encoding="utf-8"))["active_state"] == "cycle_completed"
    assert len((repo / "todo" / "results.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_todo_daemon_runner_marks_valid_task_complete(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    board = repo / "todo" / "board.md"
    board.parent.mkdir(parents=True)
    board.write_text("- [ ] Task checkbox-1: Generic reusable task.\n", encoding="utf-8")
    config = SyntheticDaemonConfig(repo_root=repo)

    def replace_task_mark(markdown: str, selected: Task, mark: str) -> str:
        return re.sub(
            r"- \[[ xX~!]\] " + re.escape(selected.label),
            f"- [{mark}] " + selected.label,
            markdown,
            count=1,
        )

    def update_generated_status(markdown: str, latest: dict[str, object], _tasks: list[Task]) -> str:
        return markdown.rstrip() + f"\n\nLatest result: {latest['result']}\n"

    def produce_proposal(
        _config: SyntheticDaemonConfig,
        _selected: Task,
        write_status,
    ) -> Proposal:
        write_status("producing_fixture", target_task=_selected.label)
        return Proposal(summary="Synthetic accepted work", files=[{"path": "todo/output.txt", "content": "ok\n"}])

    def apply_proposal(proposal: Proposal, _config: SyntheticDaemonConfig) -> Proposal:
        proposal.applied = True
        proposal.validation_results = [CommandResult(("true",), 0, "", "")]
        return proposal

    hooks = TodoDaemonHooks(
        parse_tasks=parse_markdown_tasks,
        select_task=lambda tasks, _config: next(iter(tasks), None),
        replace_task_mark=replace_task_mark,
        update_generated_status=update_generated_status,
        produce_proposal=produce_proposal,
        apply_proposal=apply_proposal,
        run_validation=lambda _config, _proposal: [CommandResult(("true",), 0, "", "")],
        should_skip_validation=lambda _proposal: False,
        is_retryable_failure=lambda _proposal: False,
        failure_block_threshold=lambda _proposal, _config: 1,
        failure_count_for_block=lambda _config, _label: 0,
        should_sleep_between_cycles=lambda _markdown, _config: False,
        exception_diagnostic=lambda exc: str(exc),
    )

    proposals = TodoDaemonRunner(config, hooks).run()
    rows = (repo / "todo" / "results.jsonl").read_text(encoding="utf-8").splitlines()
    status = json.loads((repo / "todo" / "status.json").read_text(encoding="utf-8"))

    assert proposals[-1].valid
    assert "- [x] Task checkbox-1: Generic reusable task." in board.read_text(encoding="utf-8")
    assert len(rows) == 1
    assert status["active_state"] == "cycle_completed"


def test_file_replacement_todo_daemon_runner_uses_reusable_apply_flow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    board = repo / "todo" / "board.md"
    board.parent.mkdir(parents=True)
    board.write_text("- [ ] Task checkbox-3: Concrete file runner task.\n", encoding="utf-8")
    (repo / "todo" / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    config = SyntheticDaemonConfig(repo_root=repo)
    spec = ValidationWorkspaceSpec(
        repo_root=repo,
        worktree_dir=Path(".daemon/worktrees"),
        marker_name="example-worktree.json",
        copy_paths=(Path("todo"),),
    )

    def replace_task_mark(markdown: str, selected: Task, mark: str) -> str:
        return re.sub(
            r"- \[[ xX~!]\] " + re.escape(selected.label),
            f"- [{mark}] " + selected.label,
            markdown,
            count=1,
        )

    runner_hooks = TodoDaemonHooks(
        parse_tasks=parse_markdown_tasks,
        select_task=lambda tasks, _config: next(iter(tasks), None),
        replace_task_mark=replace_task_mark,
        update_generated_status=lambda markdown, latest, _tasks: markdown.rstrip()
        + f"\n\nLatest result: {latest['result']}\n",
        produce_proposal=lambda _config, _selected, _write_status: Proposal(
            summary="Concrete accepted work",
            files=[{"path": "todo/source.py", "content": "VALUE = 3\n"}],
            requires_visible_source_change=True,
        ),
        apply_proposal=lambda proposal, _config: proposal,
        run_validation=lambda _config, _proposal: [CommandResult(("true",), 0, "", "")],
        should_skip_validation=lambda _proposal: False,
        is_retryable_failure=lambda _proposal: False,
        failure_block_threshold=lambda _proposal, _config: 1,
        failure_count_for_block=lambda _config, _label: 0,
        should_sleep_between_cycles=lambda _markdown, _config: False,
        exception_diagnostic=lambda exc: str(exc),
    )
    accepted: list[str] = []
    file_hooks = FileReplacementHooks(
        validate_write_path=lambda path: [] if path.startswith("todo/") else ["outside allowlist"],
        temporary_validation_worktree=validation_worktree_for_spec(spec),
        validation_commands_for_proposal=lambda _proposal, _config: (("synthetic-validation",),),
        run_validation=lambda _config, commands: [CommandResult(commands[0], 0, "ok", "")],
        syntax_preflight=lambda _worktree, _changed, _config: (
            [CommandResult(("synthetic-preflight",), 0, "ok", "")],
            [],
            "",
        ),
        has_visible_source_change=lambda changed: any(path.endswith(".py") for path in changed),
        attempt_validation_repair=lambda proposal, _config, _worktree: (False, proposal.changed_files, ""),
        persist_failed_work=lambda _proposal, _config, _diff_text, _reason, _transport: None,
        persist_accepted_work=lambda proposal, _config, _diff_text, _transport: accepted.append(
            proposal.summary
        ),
    )

    proposals = run_todo_daemon(
        config,
        runner_factory=lambda runner_config: FileReplacementTodoDaemonRunner(
            runner_config,
            runner_hooks,
            file_hooks,
        ),
    )
    proposal = proposals[0]
    payload = todo_daemon_proposals_payload(proposals)

    assert proposal.valid
    assert payload[0]["summary"] == "Concrete accepted work"
    assert accepted == ["Concrete accepted work"]
    assert (repo / "todo" / "source.py").read_text(encoding="utf-8") == "VALUE = 3\n"
    assert "- [x] Task checkbox-3: Concrete file runner task." in board.read_text(encoding="utf-8")


def test_todo_daemon_runner_pre_task_block_marks_task_blocked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    board = repo / "todo" / "board.md"
    board.parent.mkdir(parents=True)
    board.write_text("- [ ] Task checkbox-2: Blocked before work.\n", encoding="utf-8")
    config = SyntheticDaemonConfig(repo_root=repo)

    def replace_task_mark(markdown: str, selected: Task, mark: str) -> str:
        return re.sub(
            r"- \[[ xX~!]\] " + re.escape(selected.label),
            f"- [{mark}] " + selected.label,
            markdown,
            count=1,
        )

    hooks = TodoDaemonHooks(
        parse_tasks=parse_markdown_tasks,
        select_task=lambda tasks, _config: next(iter(tasks), None),
        replace_task_mark=replace_task_mark,
        update_generated_status=lambda markdown, latest, _tasks: markdown.rstrip()
        + f"\n\nLatest result: {latest['result']}\n",
        produce_proposal=lambda _config, _selected, _write_status: Proposal(summary="should not run"),
        apply_proposal=lambda proposal, _config: proposal,
        run_validation=lambda _config, _proposal: [],
        should_skip_validation=lambda _proposal: True,
        is_retryable_failure=lambda _proposal: False,
        failure_block_threshold=lambda _proposal, _config: 1,
        failure_count_for_block=lambda _config, _label: 0,
        should_sleep_between_cycles=lambda _markdown, _config: False,
        exception_diagnostic=lambda exc: str(exc),
        pre_task_block=lambda _config, _task: PreTaskBlock(
            summary="Blocked before work.",
            failure_kind="pre_task_block",
            result="blocked_before_work",
        ),
    )

    proposal = TodoDaemonRunner(config, hooks).run()[0]

    assert proposal.failure_kind == "pre_task_block"
    assert "- [!] Task checkbox-2: Blocked before work." in board.read_text(encoding="utf-8")
