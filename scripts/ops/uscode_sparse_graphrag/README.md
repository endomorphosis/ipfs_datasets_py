# US Code Sparse GraphRAG Supervisor Operations

This directory operates the sealed four-lane `USCIR-` board. Run it only from the clean `feature/uscode-sparse-graphrag` worktree bound by the scheduler config. The runtime namespace is `workspace/agent-supervisor/uscode-sparse-graphrag/`; it is Git-ignored and must not be shared with another board.

Set `IPFS_ACCELERATE_ROOT` to the clean `ipfs_accelerate_py` checkout containing the current configured-board scheduler. In the paired worktree layout it defaults to `../ipfs_accelerate_py`.

## Validate and render

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
ACCELERATOR_ROOT="${IPFS_ACCELERATE_ROOT:-$(cd "$REPO_ROOT/../ipfs_accelerate_py" && pwd)}"
export PYTHONPATH="$ACCELERATOR_ROOT${PYTHONPATH:+:$PYTHONPATH}"

python3 -P scripts/ops/uscode_sparse_graphrag/preflight.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_uscode_sparse_graphrag_scheduler.json \
  --json

python3 -P scripts/ops/agent_supervisor/configured_board_scheduler.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_uscode_sparse_graphrag_scheduler.json \
  launch --implement --dry-run
```

The preflight rejects dirty or wrong-branch control planes, missing tracked files, invalid boards, non-ignored runtime paths, Git operations in progress, provider contract drift, and any existing process or stale artifact using the exact namespace. It never deletes or kills anything.

## Launch

```bash
python3 -P scripts/ops/agent_supervisor/configured_board_scheduler.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_uscode_sparse_graphrag_scheduler.json \
  launch --implement
```

The default launch detaches. It uses four strict modulo lanes, a serialized merge queue, bounded retries, Grok `grok-4.5` as primary, and Codex `gpt-5.6-terra` only when the supervisor verifies primary quota exhaustion. Secrets come only from the inherited environment.

## Verify health

```bash
scripts/ops/uscode_sparse_graphrag/status.sh
scripts/ops/uscode_sparse_graphrag/status.sh --json --observe-seconds 20
```

Exit status is zero only for `starting`, `healthy`, or cryptographically/current-board-proven `completed`. Health requires exact process identity and ownership, fresh supervisor heartbeats, no duplicate/orphan process, no protected-path incident, no blocked work, bounded active worker/log age, and no ready-without-worker stall. The observed form takes two samples and rejects healthy lanes whose heartbeat and durable progress both remain unchanged.

Do not infer health from a PID alone. Do not manually start another copy when preflight reports an existing namespace. Reconcile incidents from the state/log receipts before any cleanup, and never delete a runtime tree while a matching process is live.

## Publication boundary

Implementation lanes may build, validate, stage under an explicit non-production authorization, redownload, canary, and prepare a publication-seal request. They may not update the public `justicedao/ipfs_uscode` dataset. Production publication requires an external human seal matching the exact candidate revision, manifest/evidence digests, requested mutations, and rollback target.
