# PORTAL-102 Reconciliation Guardrail

Date: 2026-07-21
Fingerprint: 0c2214156b1d0b958aa92a0c395eb9ddeb3d2809
Kind: preflight_merge_conflict
Reason: preflight_merge_conflict
Candidate count: 1
Priority: P1
Track: ops

## Main Checkout Status

- none

## Main Checkout Evidence

- none

## Sample Branches Or Worktrees

- `implementation/portal-lir-hammer-059-attempt-3-1784616584` at `/home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/hammer-leanstral-worktrees/portal-lir-hammer-059-attempt-3-1784616584`
  - Conflict paths:
    - `ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer.py`
    - `ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer_coverage.py`

## Why This Blocks Progress

The implementation supervisor can only merge clean inactive implementation
worktrees when the main checkout is safe to mutate. Dirty main checkouts and
dirty backlogged worktrees are preserved until a deliberate reconciliation task
decides whether to commit, merge, discard generated duplicates, or split
unresolved work into follow-up tasks.

## Suggested Repair

Inspect the dirty paths and sampled worktrees, resolve any real work into
reviewable commits or follow-up tasks, rerun the supervisor reconciliation pass,
and verify that either the candidate merge count decreases or the dirty
worktree cleanup skip count decreases.

## Reconciliation Plan

Work surface: `1` candidates, `1` sampled records.

### Suggested Actions

- `bundle_preflight_conflicts_by_path`: group blocked branches by shared conflict paths before resolving individual branches
- `resolve_markdown_and_discovery_conflicts_deterministically`: use deterministic append-only markdown/objective/todo merge repair where conflict paths are documentation or discovery files
- `resolve_code_or_submodule_conflicts_in_isolated_worktree`: stage conflicts in a temporary reconciliation worktree or invoke the configured LLM resolver before mutating main
- `rerun_worktree_reconciliation`: rerun reconcile_backlogged_worktrees and confirm preflight_blocked_count decreases

### Safety Constraints

- Do not run conflict-producing merges directly in main without a preflight or isolated resolver plan.
- Preserve submodule gitlink intent explicitly; never pick a gitlink side without recording why.
- Keep todo, objective, discovery, and strategy files parseable after reconciliation.

### Success Signals

- `preflight_blocked_count_decreases`
- `conflict_path_count_decreases`
- `reconciled_count_increases`
- `main_checkout_dirty_becomes_false`

## Machine Readable Manifest

```json
{
  "actions": [
    {
      "action": "bundle_preflight_conflicts_by_path",
      "automation": "group blocked branches by shared conflict paths before resolving individual branches",
      "scope": "backlogged_worktrees"
    },
    {
      "action": "resolve_markdown_and_discovery_conflicts_deterministically",
      "automation": "use deterministic append-only markdown/objective/todo merge repair where conflict paths are documentation or discovery files",
      "scope": "append_only_docs"
    },
    {
      "action": "resolve_code_or_submodule_conflicts_in_isolated_worktree",
      "automation": "stage conflicts in a temporary reconciliation worktree or invoke the configured LLM resolver before mutating main",
      "scope": "code_and_gitlinks"
    },
    {
      "action": "rerun_worktree_reconciliation",
      "automation": "rerun reconcile_backlogged_worktrees and confirm preflight_blocked_count decreases",
      "scope": "backlogged_worktrees"
    }
  ],
  "candidate_count": 1,
  "conflict_path_counts": {
    "ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer.py": 1,
    "ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer_coverage.py": 1
  },
  "dedupe_key": "reconciliation_guardrail:preflight_merge_conflict",
  "fingerprint": "0c2214156b1d0b958aa92a0c395eb9ddeb3d2809",
  "kind": "preflight_merge_conflict",
  "main_dirty_evidence": {},
  "reason": "preflight_merge_conflict",
  "safety_constraints": [
    "Do not run conflict-producing merges directly in main without a preflight or isolated resolver plan.",
    "Preserve submodule gitlink intent explicitly; never pick a gitlink side without recording why.",
    "Keep todo, objective, discovery, and strategy files parseable after reconciliation."
  ],
  "sample_branches": [
    "implementation/portal-lir-hammer-059-attempt-3-1784616584"
  ],
  "sample_count": 1,
  "sample_status_paths": [
    "ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer.py",
    "ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer_coverage.py"
  ],
  "sample_worktrees": [
    "/home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/hammer-leanstral-worktrees/portal-lir-hammer-059-attempt-3-1784616584"
  ],
  "success_signals": [
    "preflight_blocked_count_decreases",
    "conflict_path_count_decreases",
    "reconciled_count_increases",
    "main_checkout_dirty_becomes_false"
  ],
  "top_conflict_paths": [
    "ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer.py",
    "ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer_coverage.py"
  ]
}
```
