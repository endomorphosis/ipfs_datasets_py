# Logic Intent · Legal · Security Gate — multi-lane supervisor

Unified, deduplicated task board for LIG (IRF foundation absorbed).

| Item | Path |
|------|------|
| Plan | `docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md` |
| Deep authorization design | `docs/architecture/INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md` |
| Goals | `docs/architecture/logic_intent_legal_gate.objectives.md` |
| Board | `docs/architecture/logic_intent_legal_gate.todo.md` |
| Branch | `feature/logic-intent-legal-gate` |
| Namespace | `logic-intent-legal-gate-v1` |
| State root | `data/agent_supervisor/logic_intent_legal_gate/` |

## Do not co-launch

- `ir-family-v1` / IRF board (completed; would contend on `logic/**`)
- Other program supervisors sharing the same worktree or todo path

## Quick start

From `ipfs_datasets_py` repo root:

```bash
# Inspect ready tasks only
scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh --dry-run

# Four parallel shards (default)
scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh

# Single shard foreground
SHARD=0 SHARD_COUNT=4 scripts/ops/logic_intent_legal_gate/launch_multi_lane.sh --foreground
```

Environment:

| Variable | Default | Meaning |
|----------|---------|---------|
| `SHARD_COUNT` | `4` | Number of task shards |
| `SHARD` | — | Required with `--foreground` |
| `REPO_ROOT` | script-resolved | datasets repo root |
| `ACCELERATE_ROOT` | `../ipfs_accelerate_py` | for `PYTHONPATH` |
| `IMPLEMENT` | `1` | set `0` for dry-run equivalent |
| `MERGE_TARGET_BRANCH` | `feature/logic-intent-legal-gate` | merge train target (not main) |
| `MERGE_QUEUE_DIR` | auto by target | optional shared queue for all shards |

### Merge vs board completion

Validated work is **queued** into a target-scoped merge train. The durable board
stays incomplete (`merge-queued` in daemon projection) until the train integrates
into `MERGE_TARGET_BRANCH`. Do not treat todo `Status: completed` alone as
“landed on the feature branch” unless merge receipts confirm integration.

Protected paths (implementation agents cannot claim as Outputs): the four
architecture files listed above.

## Authority-hardening continuation

- **LIG-022** — canonical invocation intent envelope
- **LIG-023** — shared constraint and applicability contracts

These are the first file-exclusive continuation roots after the base LIG
pipeline. Read the board/task-state files for current readiness; base task
status can advance while the four shards run.
