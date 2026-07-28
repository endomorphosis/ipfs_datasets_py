# Logic Intent · Legal · Security Gate — multi-lane supervisor

Unified, deduplicated task board for LIG (IRF foundation absorbed).

| Item | Path |
|------|------|
| Plan | `docs/architecture/LOGIC_INTENT_LEGAL_GATE_PLAN.md` |
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

Protected paths (implementation agents cannot claim as Outputs): the three
architecture files listed above.

## Initially ready (post-absorption)

- **LIG-003** — Legal frozen CID residual
- **LIG-005** — prompt/MCP source adapters
- **LIG-009** — security constraint cache
- **LIG-014** — admissibility profiles

Completed foundation (not re-run): LIG-001, LIG-002, LIG-004, LIG-010, LIG-021.
