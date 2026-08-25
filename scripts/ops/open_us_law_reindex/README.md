# Open US Law reindex supervisor operations

This control plane is independent from the older legal-corpora and state-laws namespaces. It uses the same clean `feature/legal-corpora-reindex` target worktree and the exact paired accelerator revision sealed in the scheduler.

The source is `justicedao/open-us-law-bucket`. The authoritative query release is `justicedao/open-us-law-sparse-graphrag`; identical bytes may be mirrored additively under `releases/<manifest_sha256>/` in the Bucket. No command in this board deletes or overwrites the raw Bucket root.

## Validate and preflight

```bash
REPO_ROOT=/home/barberb/portland-laws.github.io/workspace/codex-work/legal-corpora-reindex/ipfs_datasets_py
cd "$REPO_ROOT"
python3 -P scripts/validate_open_us_law_reindex_board.py --check-all
/usr/bin/python3.12 -I -S -B scripts/ops/open_us_law_reindex/preflight.py --repo-root "$REPO_ROOT" --json
```

Preflight fails closed on a dirty/wrong branch, an untracked control file, paired-runtime drift, provider/auth failure, missing validation dependencies, stale runtime artifacts, or another live process in the same OUL namespace.

## Review and launch

```bash
python3 -I -S -B scripts/ops/agent_supervisor/configured_board_scheduler.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_open_us_law_reindex_scheduler.json \
  launch --implement --dry-run

python3 -I -S -B scripts/ops/agent_supervisor/configured_board_scheduler.py \
  --repo-root "$REPO_ROOT" \
  --config config/agent_supervisor_open_us_law_reindex_scheduler.json \
  launch --implement
```

The detached launch uses four strict SHA-256 lanes, objective and codebase refills, a serialized merge queue, Grok `grok-4.6` primary, and Codex `gpt-5.6-terra` at medium reasoning only after typed primary quota exhaustion.

A separate state-laws supervisor may still be acquiring jurisdictions. OUL-006 validates and leases its evidence so the two boards do not scrape the same jurisdiction concurrently. It never trusts the older task status or fixture receipts by themselves.

## Monitor

```bash
python3 -P scripts/ops/open_us_law_reindex/status.py \
  --repo-root "$REPO_ROOT" --json --observe-seconds 35
```

A healthy observation requires the exact master and four lane trees, fresh and advancing heartbeats, no duplicate/orphan workers, no protected-path incident, no blocked work, and active logs below the stall threshold. A PID alone is never considered healthy.

Do not delete stale state or kill a process by pattern. Resolve the exact PID, command line, namespace, and state root first; archive stopped runtime evidence outside the active runtime path before a new preflight.
