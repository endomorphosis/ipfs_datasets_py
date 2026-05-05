# Reusable Todo Daemon Module

`ipfs_datasets_py.optimizers.todo_daemon` contains the shared runner, lifecycle, supervisor, process, result-history, JSONL parsing, and temporary-worktree primitives used by optimizer daemons. New unattended todo daemons should live as small domain modules that provide configuration and hooks, then reuse this package instead of copying the logic-port shell/Python scaffolding.

## Package Entry Point

Built-in daemon lifecycle commands are available through one package dispatcher:

```bash
python3 -m ipfs_datasets_py.optimizers.todo_daemon list
python3 -m ipfs_datasets_py.optimizers.todo_daemon logic-port check
python3 -m ipfs_datasets_py.optimizers.todo_daemon logic-port ensure
python3 -m ipfs_datasets_py.optimizers.todo_daemon logic-port stop
python3 -m ipfs_datasets_py.optimizers.todo_daemon legal-parser check
```

The legacy shell wrappers remain stable, but the logic-port wrappers now delegate to the package dispatcher so future daemons can follow the same shape.

## Reuse Pattern

1. Define a `ManagedDaemonSpec` for lifecycle paths, process matching, launch environment, task board, and worktree root.
2. Build a lifecycle CLI with `build_lifecycle_arg_parser()` and `run_lifecycle_cli()`.
3. Implement `TodoDaemonHooks` for domain behavior: task parsing, task selection, proposal generation, validation, task-board status updates, retry policy, and exception diagnostics.
4. Use `run_todo_daemon()` or `run_todo_daemon_cli()` as the daemon entry point. Pass `hooks_factory` for a plain `TodoDaemonRunner`, or `runner_factory` when the daemon needs a specialized runner such as `FileReplacementTodoDaemonRunner`.
5. Use `TodoDaemonRunner` for heartbeat, progress JSON, task-board marking, result logs, watch-loop handling, and crash capture.
6. Use `run_command()` for validation and git commands so timeouts clean up the full process group and optional stdin is captured consistently.
7. Use `extract_json()`, `extract_codex_event_text_candidates()`, and `looks_like_empty_codex_event_stream()` when proposal output may arrive as Codex JSONL events rather than plain JSON.
8. Use `read_daemon_results()`, `recent_failure_count()`, `current_task_failure_counts()`, and `task_failure_summary()` for retry budgets, blocked-task decisions, and self-repair context.
9. Use `cleanup_stale_daemon_worktrees()`, `write_worktree_owner_file()`, and `pid_looks_like_worktree_owner()` for temporary worktree ownership, stale-worktree garbage collection, and crash recovery.
10. Use `SupervisedChildSpec`, `launch_supervised_child()`, `wait_for_child_exit()`, `clear_child_pid_file()`, `RestartPolicy`, and `supervised_log_path()` when a supervisor needs to launch a long-running module child with durable logs, PID markers, latest-log symlinks, and consistent restart delays.
11. For complete-file edits, bind `FileReplacementHooks` through `FileReplacementTodoDaemonRunner`, `build_file_replacement_apply_proposal()`, or `apply_file_replacement_proposal()` so candidate changes are written in a temporary validation worktree and promoted only after validation succeeds.

This keeps future daemons deterministic at the control-flow layer: lifecycle management, task bookkeeping, repair-safe worktrees, and durable progress reporting stay shared, while each daemon owns only its task interpretation and proposal-production logic.
