# Reusable Todo Daemon Module

`ipfs_datasets_py.optimizers.todo_daemon` contains the shared runner, lifecycle, supervisor, process, result-history, diagnostic-loop, JSONL parsing, and temporary-worktree primitives used by optimizer daemons. New unattended todo daemons should live as small domain modules that provide configuration and hooks, then reuse this package instead of copying the logic-port shell/Python scaffolding.

## Package Entry Point

Built-in daemon lifecycle commands are available through one package dispatcher:

```bash
python3 -m ipfs_datasets_py.optimizers.todo_daemon list
python3 -m ipfs_datasets_py.optimizers.todo_daemon logic-port check
python3 -m ipfs_datasets_py.optimizers.todo_daemon logic-port ensure
python3 -m ipfs_datasets_py.optimizers.todo_daemon logic-port stop
python3 -m ipfs_datasets_py.optimizers.todo_daemon logic-port run -- --help
python3 -m ipfs_datasets_py.optimizers.todo_daemon legal-parser check
python3 -m ipfs_datasets_py.optimizers.todo_daemon legal-parser run -- --help
python3 -m ipfs_datasets_py.optimizers.todo_daemon supervise --help
```

The legacy shell wrappers remain stable, but they delegate to the package dispatcher so future daemons can follow the same shape.
For direct `python -m` invocation in environments without `ipfs_accelerate_py`, set `IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE=0`; the maintained lifecycle shell wrappers already do this.

## Reuse Pattern

1. Define a `ManagedDaemonSpec` for lifecycle paths, process matching, launch environment, task board, and worktree root. Use `env_value()`, `env_flag()`, `env_int()`, `env_float()`, `env_path()`, `env_path_in_dir()`, and `repo_root_from_env()` for env-backed daemon defaults instead of duplicating path plumbing.
2. Register package-dispatched daemon families with `TodoDaemonRegistration` in the todo-daemon registry, including stable aliases for legacy command names.
3. Build a lifecycle CLI with `build_lifecycle_arg_parser()` and `run_lifecycle_cli()`. Pass `run_description` and `run_fn` when the daemon should expose its foreground runtime through the same package dispatcher.
4. Implement `TodoDaemonHooks` for domain behavior: task parsing, task selection, proposal generation, validation, task-board status updates, retry policy, and exception diagnostics.
5. Use `run_todo_daemon()` or `run_todo_daemon_cli()` as the daemon entry point. Pass `hooks_factory` for a plain `TodoDaemonRunner`, or `runner_factory` when the daemon needs a specialized runner such as `FileReplacementTodoDaemonRunner`.
6. Use `TodoDaemonRunner` for heartbeat, progress JSON, task-board marking, result logs, watch-loop handling, and crash capture. Use `task_status_counts()`, `replace_task_mark()`, `should_sleep_between_task_cycles()`, `update_generated_status_block()`, `strip_unmanaged_generated_status_sections()`, `focused_task_board_excerpt()`, and `truncate_text()` when a daemon needs reusable markdown generated-status blocks, checkbox transitions, immediate/no-sleep watch-loop decisions, or compact task-board prompt excerpts.
7. Use `plan_task_from_latest_result()`, `select_next_plan_task()`, `select_blocked_plan_task()`, `build_blocked_task_backlog()`, and `blocked_task_backlog_markdown()` when a daemon needs Markdown-plan task matching, blocked-task revisit strategies, or compact blocked-backlog prompts.
8. Use `task_title_tokens()`, `rank_relevant_context_file()`, `select_relevant_context_paths()`, and `render_relevant_file_context()` when a daemon needs task-aware prompt context from a tracked-file inventory without copying repository-specific ranking code.
9. Use `run_command()`, `validation_commands_for_proposal()`, and `run_validation_commands()` for validation and git commands so trusted proposal commands, daemon defaults, timeouts, full-process-group cleanup, optional stdin, and result capture are consistent.
10. Use `AutoCommitConfig`, `safe_auto_commit_pathspecs()`, `build_auto_commit_subject()`, and `auto_commit_paths()` when validated daemon work should be committed automatically from an explicit allowlist.
11. Use `extract_json()`, `extract_codex_event_text_candidates()`, and `looks_like_empty_codex_event_stream()` when proposal output may arrive as Codex JSONL events rather than plain JSON.
12. Use `read_daemon_results()` for legacy result/artifact rows, or `read_daemon_proposal_records()`, `recent_proposal_failures()`, `should_use_compact_prompt_for_failures()`, `recent_failure_count()`, `current_task_failure_counts()`, and `task_failure_summary()` for runner proposal logs, retry budgets, blocked-task decisions, compact prompts, and self-repair context.
13. Use `artifact_validation_text()`, `diagnostic_signatures()`, `exception_diagnostic()`, `format_recent_failure_context()`, `FailureBlockRule`, `first_failure_block_decision()`, `is_retryable_proposal_failure()`, `should_skip_validation_for_empty_proposal()`, `proposal_block_threshold()`, `prompt_limit_for_mode()`, `count_proposal_records_with_failure_markers()`, `quality_failure_counts()`, `rollback_failure_counts()`, and `recent_rollback_failure_count()` when a daemon needs to detect repeated failures, build repair prompts, capture compact crash diagnostics, skip wasted validation, compact prompts, replenish, repair, retry, or block tasks.
14. Use `build_blocked_task_backlog()`, `blocked_task_backlog_markdown()`, `select_blocked_plan_task()`, and `select_next_plan_task()` when a daemon needs consistent blocked-task revisits, backlog rendering, and open-task selection across markdown plan formats.
15. Use `fallback_kind_for_task()`, `task_has_deterministic_fallback()`, `load_deterministic_progress_manifest()`, `build_deterministic_progress_record()`, `upsert_deterministic_progress_record()`, and `build_deterministic_replacement_proposal()` when a daemon needs fixture-only fallback work that can proceed without a healthy LLM while still recording a deterministic progress manifest.
16. Use `LlmRouterInvocation`, `call_llm_router()`, `install_active_llm_signal_handlers()`, and `terminate_process_group()` when a daemon needs an isolated `llm_router.generate_text` child with prompt-file handoff, timeout cleanup, optional trace forwarding, local-fallback rejection, and signal-safe process-group termination.
17. Use `cleanup_stale_daemon_worktrees()`, `write_worktree_owner_file()`, and `pid_looks_like_worktree_owner()` for temporary worktree ownership, stale-worktree garbage collection, and crash recovery.
18. Use `SupervisedChildSpec`, `launch_supervised_child()`, `wait_for_child_exit()`, `clear_child_pid_file()`, `RestartPolicy`, and `supervised_log_path()` when a supervisor needs to launch a long-running module child with durable logs, PID markers, latest-log symlinks, and consistent restart delays.
19. Use `SupervisorLoop`, `SupervisorLoopConfig`, `build_supervisor_loop_arg_parser()`, `supervisor_loop_config_from_args()`, and `run_supervisor_loop_cli()` for a full Python supervisor that launches module children, polls child exits promptly, writes supervisor status JSON, monitors stale heartbeats and workerless worktree phases, recycles unhealthy children, and applies restart policy delays.
20. Use `accepted_work_manifest()`, `failed_work_manifest()`, `write_work_sidecars()`, `accepted_work_evidence_manifest()`, `accepted_work_markdown_entry()`, `append_accepted_work_markdown_log()`, `build_accepted_work_ledger_entry()`, and `append_jsonl_ledger()` when a daemon needs compact accepted/failed work evidence, optional sidecars, diff/stat files, markdown audit logs, and append-only ledgers without reimplementing artifact naming and validation-result compaction.
21. For complete-file edits, bind `FileReplacementHooks` through `FileReplacementTodoDaemonRunner`, `build_file_replacement_apply_proposal()`, or `apply_file_replacement_proposal()` so candidate changes are written in a temporary validation worktree and promoted only after validation succeeds.

This keeps future daemons deterministic at the control-flow layer: lifecycle management, task bookkeeping, repair-safe worktrees, and durable progress reporting stay shared, while each daemon owns only its task interpretation and proposal-production logic.
