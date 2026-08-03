# Patent legal intelligence supervisor

This program runs the reviewed
`docs/architecture/patent_legal_intelligence.todo.md` projection through four
strict, explicit implementation slices. Each shard has isolated state/logs/
worktrees, while all shards share one merge queue targeting
`feature/patent-legal-intelligence`. Runtime state defaults outside git to
`~/.local/state/ipfs_accelerate_py/patent-legal-intelligence-v1`.

## Validate, start, and inspect

```bash
# Repository/provider/supervisor check; does not implement.
scripts/ops/patent_legal_intelligence/preflight.py

# Exercise all four task slices once without implementation.
scripts/ops/patent_legal_intelligence/launch_multi_lane.sh --dry-run

# Start four detached, restartable supervisors.
scripts/ops/patent_legal_intelligence/launch_multi_lane.sh

# Content-free PID/heartbeat/worker/readiness/incident/merge status.
scripts/ops/patent_legal_intelligence/status.sh
scripts/ops/patent_legal_intelligence/status.sh --json
```

Use the `PATLAW_*` environment variables documented by the launcher when the
datasets and accelerator feature worktrees are not siblings. The launcher uses
`python3 -P` with an explicit `PYTHONPATH` to prevent the datasets repository's
nested legacy accelerator package from shadowing the selected supervisor.

## Provider and board policy

Implementation uses `auto`: authenticated Grok (`grok-4.5`) is primary and
Codex (`gpt-5.6-terra`, high reasoning effort) is available only through the
reviewed fresh-attempt fallback. A failed provider's worktree is discarded;
the backup begins from the same clean base with a separate receipt. The task
graph is execution-only: automatic objective/codebase refill, goal mutation,
task janitor, and generated repair guardrails are disabled. Implementation
agents cannot edit protected plan, heap, board, configuration, policies, or
operator scripts.

The supervisor may update its external runtime projection and merge receipts;
it does not infer completion from Markdown status alone. Never run `git pull`
inside an active lane or co-launch another program over this state namespace.
Read-only fetch can occur at the reviewed intervals, but integration is a
separate serialized, checkpointed operator maintenance event; implementation
lanes do not pull. Patent Center remains authorized user export/import only—
never login, MFA, signature, payment, or filing automation.

To stop this program, send `TERM` only to the exact live PIDs recorded under
`$PATLAW_STATE_ROOT/shards/*/supervisor.pid` (or the default state root), then
verify they exited with `status.sh`. Do not use broad process-name kills.
