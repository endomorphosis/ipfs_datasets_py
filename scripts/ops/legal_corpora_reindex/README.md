# Legal Corpora Reindex Supervisor Operations

This directory operates the sealed four-lane `LCR-` board. Run it only from the clean `feature/legal-corpora-reindex` worktree bound by the scheduler config. The runtime namespace is `workspace/agent-supervisor/legal-corpora-reindex/`; it is Git-ignored and must not be shared with another board.

Set `IPFS_ACCELERATE_ROOT` to the clean `ipfs_accelerate_py` checkout containing the current configured-board scheduler. In the paired worktree layout it defaults to `../ipfs_accelerate_py`.

## Validate and render

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
ACCELERATOR_ROOT="${IPFS_ACCELERATE_ROOT:-$(cd "$REPO_ROOT/../ipfs_accelerate_py" && pwd)}"
export PYTHONPATH="$ACCELERATOR_ROOT${PYTHONPATH:+:$PYTHONPATH}"

python3 -P scripts/ops/legal_corpora_reindex/preflight.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_legal_corpora_reindex_scheduler.json \
  --json

python3 -P scripts/ops/agent_supervisor/configured_board_scheduler.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_legal_corpora_reindex_scheduler.json \
  launch --implement --dry-run
```

The preflight rejects dirty or wrong-branch control planes, missing tracked files, invalid boards, non-ignored runtime paths, Git operations in progress, provider contract drift, and any existing process or stale artifact using the exact namespace. It never deletes or kills anything.

## Launch

```bash
python3 -P scripts/ops/agent_supervisor/configured_board_scheduler.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_legal_corpora_reindex_scheduler.json \
  launch --implement
```

The default launch detaches. It uses four strict full-task-ID SHA-256 lanes, a serialized merge queue, bounded retries and refills, Grok `grok-4.5` as primary, and Codex `gpt-5.6-terra` only when the supervisor verifies primary quota exhaustion. Secrets come only from the inherited environment.

## Verify health

```bash
scripts/ops/legal_corpora_reindex/status.sh
scripts/ops/legal_corpora_reindex/status.sh --json --observe-seconds 20
```

Exit status is zero only for `starting`, `healthy`, or cryptographically/current-board-proven `completed`. Health requires exact process identity and ownership, fresh supervisor heartbeats, no duplicate/orphan process, no protected-path incident, no blocked work, bounded active worker/log age even when a worker PID remains live, and no ready-without-worker stall. Host-native workers are bound by process ancestry; isolated Grok/Codex workers behind a container shim are bound to the exact active task worktree recorded by the lane. The observed form takes two samples and rejects healthy lanes whose heartbeat and durable progress both remain unchanged.

Do not infer health from a PID alone. Do not manually start another copy when preflight reports an existing namespace. Reconcile incidents from the state/log receipts before any cleanup, and never delete a runtime tree while a matching process is live.

## Publication boundary

The operator's 2026-08-10 request authorizes additive publication to exactly `justicedao/ipfs_state_laws` and `justicedao/ipfs_federal_register`. Each production task must first create a manifest-bound authorization receipt, pass a live immutable staging redownload/canary, preserve the prior public pin, and use cached/environment credentials without exposing them. The authorization does not permit deletion, force-push, history rewrite, visibility change, credential changes, or publication to any other repository.
