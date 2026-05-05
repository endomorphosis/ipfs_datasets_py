from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ipfs_datasets_py.optimizers.todo_daemon import (
    ACCEPTED_WORK_LEDGER_SCHEMA_VERSION,
    AcceptedWorkEvidencePaths,
    AutoCommitConfig,
    CommandResult,
    DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
    FailureBlockRule,
    FileReplacementHooks,
    FileReplacementTodoDaemonRunner,
    LifecycleWrapperSpec,
    LlmRouterInvocation,
    ManagedDaemonSpec,
    PathPolicy,
    PlanTask,
    PreTaskBlock,
    Proposal,
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
    WorkSidecarPaths,
    accepted_work_evidence_manifest,
    accepted_work_manifest,
    accepted_work_markdown_entry,
    accepted_work_workspace_payload,
    append_accepted_work_markdown_log,
    apply_file_replacement_proposal,
    append_jsonl_ledger,
    artifact_validation_text,
    as_repo_path,
    auto_commit_paths,
    block_threshold_for_failure_kind,
    blocked_task_backlog_markdown,
    build_auto_commit_subject,
    build_accepted_work_ledger_entry,
    build_blocked_task_backlog,
    build_deterministic_progress_record,
    build_deterministic_replacement_proposal,
    build_file_replacement_apply_proposal,
    build_lifecycle_arg_parser,
    build_python_module_command,
    build_restart_loop_command,
    build_supervisor_loop_arg_parser,
    build_supervisor_status_payload,
    build_todo_runner_arg_parser,
    call_llm_router,
    canonical_daemon_names,
    clear_child_pid_file,
    cleanup_stale_daemon_worktrees,
    compact_status_artifact,
    compact_validation_result,
    count_proposal_records_with_failure_markers,
    count_recent_proposal_failures,
    count_unmanaged_generated_status_sections,
    current_task_failure_counts,
    daemon_alias_map,
    daemon_registry_payload,
    daemon_spec_payload,
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
    lifecycle_wrapper_payload,
    load_deterministic_progress_manifest,
    load_daemon_main,
    looks_like_empty_codex_event_stream,
    managed_status_block_pattern,
    markdown_task_label,
    materialize_proposal_files,
    match_diagnostic_edit_path,
    owner_pid_from_worktree,
    open_task_has_deterministic_fallback,
    parse_json_proposal,
    parse_markdown_tasks,
    plan_task_from_latest_result,
    paths_from_file_edits,
    paths_from_git_status_porcelain,
    paths_from_patch_and_file_edits,
    paths_from_unified_diff,
    prompt_limit_for_mode,
    proposal_block_threshold,
    proposal_diff_from_worktree,
    proposal_error_text,
    promote_worktree_files,
    proposal_record_has_failure_markers,
    quality_failure_counts,
    quoted_env_assignments,
    read_daemon_results,
    read_daemon_proposal_records,
    read_json_object,
    repo_relative_pathspec,
    recent_failure_count,
    recent_proposal_failures,
    recent_rollback_failure_count,
    recent_total_failure_count,
    replace_task_mark,
    resolve_daemon_module,
    rank_relevant_context_file,
    repo_root_from_env,
    render_relevant_file_context,
    render_lifecycle_wrapper,
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
    strip_unmanaged_generated_status_sections,
    supervised_log_path,
    supervisor_run_id,
    task_failure_summary,
    task_has_deterministic_fallback,
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
    verify_promoted_worktree_files,
    wait_for_child_exit,
    worktree_phase_worker_status,
    write_json,
    write_accepted_work_evidence_artifacts,
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
        validation_results=[result.compact() for result in proposal.validation_results],
        diff_text=diff_text,
        promotion_verified=proposal.promotion_verified,
        created_at="2026-05-05T01:02:03Z",
    )
    ledger_path = append_jsonl_ledger(
        artifact_dir,
        ledger_entry,
        filename=DEFAULT_ACCEPTED_WORK_LEDGER_FILENAME,
    )
    evidence_manifest = accepted_work_evidence_manifest(
        timestamp="20260505T010203Z",
        target_task=proposal.target_task,
        summary=proposal.summary,
        impact=proposal.impact,
        changed_files=proposal.changed_files,
        validation_results=[result.compact() for result in proposal.validation_results],
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
        validation_results=[result.compact() for result in proposal.validation_results],
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
    assert json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])["summary"] == proposal.summary
    assert compact_validation_result({"command": "bad", "returncode": "not-int"}) == {
        "command": [],
        "returncode": 1,
    }
    assert evidence_manifest["validation"] == [{"command": ["pytest", "-q"], "returncode": 0}]
    assert evidence_manifest["diff_available"] is True
    assert validation_command_summaries([{"command": ["pytest", "-q"], "returncode": 0}, "ignored"]) == [
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
    spec = ValidationWorkspaceSpec(
        repo_root=repo,
        worktree_dir=Path(".daemon/worktrees"),
        marker_name="example-worktree.json",
        copy_paths=(Path("todo"), Path("docs/PLAN.md")),
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


def test_lifecycle_wrapper_renderer_matches_legacy_shell_shape() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cases = [
        (
            LifecycleWrapperSpec(
                daemon="logic-port",
                command="check",
                repo_root_ancestor="../../../..",
                pythonpath_expr="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}",
            ),
            repo_root / "scripts/ops/legal_data/check_logic_port_daemon.sh",
        ),
        (
            LifecycleWrapperSpec(
                daemon="logic-port",
                command="ensure",
                repo_root_ancestor="../../../..",
                pythonpath_expr="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}",
            ),
            repo_root / "scripts/ops/legal_data/ensure_logic_port_daemon.sh",
        ),
        (
            LifecycleWrapperSpec(
                daemon="logic-port",
                command="stop",
                repo_root_ancestor="../../../..",
                pythonpath_expr="$REPO_ROOT/ipfs_datasets_py${PYTHONPATH:+:$PYTHONPATH}",
            ),
            repo_root / "scripts/ops/legal_data/stop_logic_port_daemon.sh",
        ),
        (
            LifecycleWrapperSpec(
                daemon="legal-parser",
                command="check",
                repo_root_ancestor="../../..",
                pythonpath_expr="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}",
            ),
            repo_root / "scripts/ops/legal_data/check_legal_parser_optimizer_daemon.sh",
        ),
        (
            LifecycleWrapperSpec(
                daemon="legal-parser",
                command="ensure",
                repo_root_ancestor="../../..",
                pythonpath_expr="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}",
            ),
            repo_root / "scripts/ops/legal_data/ensure_legal_parser_optimizer_daemon.sh",
        ),
        (
            LifecycleWrapperSpec(
                daemon="legal-parser",
                command="stop",
                repo_root_ancestor="../../..",
                pythonpath_expr="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}",
            ),
            repo_root / "scripts/ops/legal_data/stop_legal_parser_optimizer_daemon.sh",
        ),
    ]

    for spec, script_path in cases:
        script = script_path.read_text(encoding="utf-8")
        payload = lifecycle_wrapper_payload(spec)
        for line in lifecycle_wrapper_core_lines(spec):
            assert line in script
        assert payload["daemon"] == spec.daemon
        assert payload["command"] == spec.command

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
        temporary_validation_worktree=lambda _config: temporary_validation_worktree(spec),
        materialize_proposal_in_worktree=lambda proposal, _config, worktree: materialize_proposal_files(
            proposal,
            worktree,
        ),
        proposal_diff_from_worktree=lambda _config, worktree, changed: proposal_diff_from_worktree(
            repo,
            worktree,
            changed,
        ),
        validation_commands_for_proposal=lambda _proposal, _config: (("synthetic-validation",),),
        run_validation=lambda _config, commands: [CommandResult(commands[0], 0, "ok", "")],
        worktree_config=lambda _config, worktree: SyntheticDaemonConfig(repo_root=worktree),
        syntax_preflight=lambda _worktree, _changed, _config: (
            [CommandResult(("synthetic-preflight",), 0, "ok", "")],
            [],
            "",
        ),
        has_visible_source_change=lambda changed: any(path.endswith(".py") for path in changed),
        attempt_validation_repair=lambda proposal, _config, _worktree: (False, proposal.changed_files, ""),
        proposal_files_from_worktree=lambda _worktree, _changed: [],
        promote_worktree_files=lambda _config, worktree, changed: promote_worktree_files(repo, worktree, changed),
        verify_promoted_worktree_files=lambda _config, worktree, changed: verify_promoted_worktree_files(
            repo,
            worktree,
            changed,
        ),
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
        materialize_proposal_in_worktree=lambda _proposal, _config, _worktree: [],
        proposal_diff_from_worktree=lambda _config, _worktree, _changed: "",
        validation_commands_for_proposal=lambda _proposal, _config: (),
        run_validation=lambda _config, _commands: [],
        worktree_config=lambda _config, worktree: SyntheticDaemonConfig(repo_root=worktree),
        syntax_preflight=lambda _worktree, _changed, _config: ([], [], ""),
        has_visible_source_change=lambda _changed: False,
        attempt_validation_repair=lambda proposal, _config, _worktree: (False, proposal.changed_files, ""),
        proposal_files_from_worktree=lambda _worktree, _changed: [],
        promote_worktree_files=lambda _config, _worktree, _changed: None,
        verify_promoted_worktree_files=lambda _config, _worktree, _changed: [],
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
        temporary_validation_worktree=lambda _config: temporary_validation_worktree(spec),
        materialize_proposal_in_worktree=lambda proposal, _config, worktree: materialize_proposal_files(
            proposal,
            worktree,
        ),
        proposal_diff_from_worktree=lambda _config, worktree, changed: proposal_diff_from_worktree(
            repo,
            worktree,
            changed,
        ),
        validation_commands_for_proposal=lambda _proposal, _config: (("synthetic-validation",),),
        run_validation=lambda _config, commands: [CommandResult(commands[0], 0, "ok", "")],
        worktree_config=lambda _config, worktree: SyntheticDaemonConfig(repo_root=worktree),
        syntax_preflight=lambda _worktree, _changed, _config: (
            [CommandResult(("synthetic-preflight",), 0, "ok", "")],
            [],
            "",
        ),
        has_visible_source_change=lambda changed: any(path.endswith(".py") for path in changed),
        attempt_validation_repair=lambda proposal, _config, _worktree: (False, proposal.changed_files, ""),
        proposal_files_from_worktree=lambda _worktree, _changed: [],
        promote_worktree_files=lambda _config, worktree, changed: promote_worktree_files(repo, worktree, changed),
        verify_promoted_worktree_files=lambda _config, worktree, changed: verify_promoted_worktree_files(
            repo,
            worktree,
            changed,
        ),
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
