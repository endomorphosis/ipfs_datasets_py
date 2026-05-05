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

The legacy shell wrappers remain stable, but the logic-port wrappers now delegate to the package dispatcher so future daemons can follow the same shape.

## Reuse Pattern

1. Define a `ManagedDaemonSpec` for lifecycle paths, process matching, launch environment, task board, and worktree root.
2. Build a lifecycle CLI with `build_lifecycle_arg_parser()` and `run_lifecycle_cli()`. Pass `run_description` and `run_fn` when the daemon should expose its foreground runtime through the same package dispatcher.
3. Implement `TodoDaemonHooks` for domain behavior: task parsing, task selection, proposal generation, validation, task-board status updates, retry policy, and exception diagnostics.
4. Use `run_todo_daemon()` or `run_todo_daemon_cli()` as the daemon entry point. Pass `hooks_factory` for a plain `TodoDaemonRunner`, or `runner_factory` when the daemon needs a specialized runner such as `FileReplacementTodoDaemonRunner`.
5. Use `TodoDaemonRunner` for heartbeat, progress JSON, task-board marking, result logs, watch-loop handling, and crash capture. Use `task_status_counts()`, `update_generated_status_block()`, `strip_unmanaged_generated_status_sections()`, `focused_task_board_excerpt()`, and `truncate_text()` when a daemon needs reusable markdown generated-status blocks or compact task-board prompt excerpts.
6. Use `run_command()` for validation and git commands so timeouts clean up the full process group and optional stdin is captured consistently.
7. Use `extract_json()`, `extract_codex_event_text_candidates()`, and `looks_like_empty_codex_event_stream()` when proposal output may arrive as Codex JSONL events rather than plain JSON.
8. Use `read_daemon_results()` for legacy result/artifact rows, or `read_daemon_proposal_records()`, `recent_proposal_failures()`, `should_use_compact_prompt_for_failures()`, `recent_failure_count()`, `current_task_failure_counts()`, and `task_failure_summary()` for runner proposal logs, retry budgets, blocked-task decisions, compact prompts, and self-repair context.
9. Use `artifact_validation_text()`, `diagnostic_signatures()`, `is_retryable_proposal_failure()`, `should_skip_validation_for_empty_proposal()`, `proposal_block_threshold()`, `prompt_limit_for_mode()`, `quality_failure_counts()`, `rollback_failure_counts()`, and `recent_rollback_failure_count()` when a daemon needs to detect repeated failures, skip wasted validation, compact prompts, replenish, repair, retry, or block tasks.
10. Use `LlmRouterInvocation`, `call_llm_router()`, `install_active_llm_signal_handlers()`, and `terminate_process_group()` when a daemon needs an isolated `llm_router.generate_text` child with prompt-file handoff, timeout cleanup, optional trace forwarding, local-fallback rejection, and signal-safe process-group termination.
11. Use `cleanup_stale_daemon_worktrees()`, `write_worktree_owner_file()`, and `pid_looks_like_worktree_owner()` for temporary worktree ownership, stale-worktree garbage collection, and crash recovery.
12. Use `SupervisedChildSpec`, `launch_supervised_child()`, `wait_for_child_exit()`, `clear_child_pid_file()`, `RestartPolicy`, and `supervised_log_path()` when a supervisor needs to launch a long-running module child with durable logs, PID markers, latest-log symlinks, and consistent restart delays.
13. Use `SupervisorLoop`, `SupervisorLoopConfig`, `build_supervisor_loop_arg_parser()`, `supervisor_loop_config_from_args()`, and `run_supervisor_loop_cli()` for a full Python supervisor that launches module children, polls child exits promptly, writes supervisor status JSON, monitors stale heartbeats and workerless worktree phases, recycles unhealthy children, and applies restart policy delays.
14. For complete-file edits, bind `FileReplacementHooks` through `FileReplacementTodoDaemonRunner`, `build_file_replacement_apply_proposal()`, or `apply_file_replacement_proposal()` so candidate changes are written in a temporary validation worktree and promoted only after validation succeeds.

This keeps future daemons deterministic at the control-flow layer: lifecycle management, task bookkeeping, repair-safe worktrees, and durable progress reporting stay shared, while each daemon owns only its task interpretation and proposal-production logic.
