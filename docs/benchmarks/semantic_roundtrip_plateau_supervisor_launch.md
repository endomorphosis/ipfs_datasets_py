# Plateau Supervisor Materializer & Launch (PLAT-070)

**Interface:** `PlateauSupervisorMaterializer@1`  
**Schema:** `ipfs-datasets.semantic-roundtrip-plateau-supervisor-materializer.v1`  
**Module:** `benchmarks.semantic_roundtrip.plateau_supervisor_materialize`  
**Evidence:** `PLATEV070SUP`  
**Depends on:** `PlateauCodexPacket@1` (PLAT-020)

## Purpose

The materializer turns sealed prover-gated Codex packets into agent-supervisor
work items for the plateau-break program:

| Packet | Materializer output |
| --- | --- |
| `implementable=true` | Edit **task** with `predicted_files` limited to **typed_deontic / realizer / tests** |
| `implementable=false` | **Obligation-only note** listing `proof_obligation_ids` (no silent merge) |

Proof pass is never promotion evidence. Every receipt and note carries
`semantic_authority=false`. The daemon merges only after structural
re-admission, packet validation commands, and pilot re-score gates.

## Doctrine

```text
PlateauCodexPacket@1
  packet_digest verified
        │
        ├─ implementable=true
        │    → MaterializedKind.IMPLEMENTABLE
        │    → predicted_files ⊆ {typed_deontic, realizer/, unit tests}
        │    → validation_commands from packet
        │    → admitted ΔL1 + residual/proposal provenance
        │    → authorize_merge=false (gates still required)
        │
        └─ implementable=false
             → MaterializedKind.OBLIGATION_ONLY
             → proof_obligation_ids listed
             → predicted_files empty; no edit surface
             → do not merge candidate L1
```

## Predicted-file surface (stricter than packet allowlist)

Packet construction may reference docs and other package modules. The
**materializer** filters edit authority to:

| Allowed path | Role |
| --- | --- |
| `benchmarks/semantic_roundtrip/constructors/typed_deontic.py` | Deterministic compiler (primary) |
| `benchmarks/semantic_roundtrip/realizers/` | Deterministic realizer (only if cycle residual requires it) |
| `tests/unit/benchmarks/semantic_roundtrip/` | Unit / contract tests |

Rejected by the materializer (examples):

- `docs/benchmarks/**` (docs-only; not an edit-wave surface)
- Optional teacher constructors (`modal_spacy`, Leanstral, AE guidance)
- Absolute paths, `..` traversal, unrelated trees

Default predicted files for implementable tasks when the packet surface is
empty or fully filtered:

```text
benchmarks/semantic_roundtrip/constructors/typed_deontic.py
tests/unit/benchmarks/semantic_roundtrip/
```

## Case → edit-wave mapping

| Pilot case | Edit-wave task |
| --- | --- |
| `legal_doc_1` | PLAT-081 |
| `construction_contract` | PLAT-082 |
| `corp_policy_1` | PLAT-083 |
| `exec_order_1` | PLAT-084 |

Materialized tasks set `edit_wave_task_id` when `case_id` matches. Parallel
lanes (`plat-det-*`) coordinate merges that touch the same typed_deontic
regions via the supervisor merge train.

## Public API

| Symbol | Role |
| --- | --- |
| `materialize_packet` | One packet → task or obligation-only note |
| `materialize_packets` | Batch → `MaterializerReceipt` |
| `filter_supervisor_predicted_files` | Enforce typed_deontic/realizer/tests allowlist |
| `coerce_packet` | Dict / JSON / object → sealed packet (digest-checked) |
| `MaterializedSupervisorItem` | Sealed task or note record |
| `MaterializerReceipt` | Batch receipt with digest |
| `BundleSupervisorLaunchSpec` | Launch flags (merge branch, max lanes, …) |
| `default_launch_spec` / `render_launch_markdown` | Operator helpers |
| `main` | CLI: materialize JSON packets or `--print-launch` |

### CLI

```bash
# Materialize sealed packet JSON → receipt + markdown board fragment
PYTHONPATH=. python -m benchmarks.semantic_roundtrip.plateau_supervisor_materialize \
  path/to/packets.json \
  --output workspace/benchmarks/semantic-roundtrip-compositions/plateau_materializer_receipt.json \
  --markdown /tmp/plat-materialized.todo.md

# Print launch snippet (flags, merge branch, max lanes)
PYTHONPATH=. python -m benchmarks.semantic_roundtrip.plateau_supervisor_materialize \
  --print-launch
```

Input JSON may be a single packet object, a JSON array of packets, or
`{"packets": [ ... ]}`.

## Launch: `bundle_supervisor` flags

Plateau-break uses the same dynamic bundle supervisor entry point as other
semantic-roundtrip boards, with a **merge target branch** and **max lanes**
tuned for foundation + case-parallel edit waves.

### Sealed launch constants

| Constant | Default |
| --- | --- |
| **Merge target branch** | `benchmark/semantic-roundtrip-20260726` |
| **Max lanes** | `4` |
| **Task prefix** | `## PLAT-` |
| **Board namespace** | `semantic-roundtrip-plateau-break-v1` |
| **Runtime root** | `/var/tmp/hssl-srt-plateau-break` |
| **Module** | `ipfs_accelerate_py.agent_supervisor.objectives.bundle_supervisor` |

### Required / primary flags

| Flag | Purpose |
| --- | --- |
| `--bundle-index-path` | Queryable bundle index (`$RUNTIME/bundles/index.json`) |
| `--repo-root` | Checkout / worktree base for implementation |
| `--state-root` | Supervisor durable state (`$RUNTIME/state`) |
| `--worktree-root` | Isolated lane worktrees (`$RUNTIME/worktrees`) |
| `--task-prefix` | Task heading prefix (`## PLAT-`) |
| `--max-lanes` | Maximum concurrent leased workers (**default 4**) |
| `--merge-target-branch` | Branch that receives each isolated lane merge |
| `--implement` | Enable implementation daemon leases |
| `--start` | Launch planned lane supervisors |

Additional supported flags (see `bundle_supervisor` argparse): `--poll-interval`,
`--once` (not a dry-run substitute), `--daemon-interval`, `--stale-seconds`,
`--implementation-timeout`, `--no-implement`, bundle-index refresh command, and
merge reconciliation knobs. Prefer the scheduler `plan` path for dry planning.

### Operator launch sketch

```bash
# From ipfs_datasets_py repo root / SRT worktree
export PYTHONPATH=ipfs_accelerate_py:.
export IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER=grok   # or project default

# Optional: project taskboard → bundle index (when scheduler config exists)
python -m benchmarks.semantic_roundtrip_scheduler prepare \
  --repo-root "$REPO" \
  --config-path config/semantic_roundtrip_plateau_break_scheduler.json \
  --runtime-root /var/tmp/hssl-srt-plateau-break \
  --taskboard-path docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md

# Launch dynamic lanes against the plateau-break board
python -m ipfs_accelerate_py.agent_supervisor.objectives.bundle_supervisor \
  --bundle-index-path /var/tmp/hssl-srt-plateau-break/bundles/index.json \
  --repo-root "$REPO" \
  --state-root /var/tmp/hssl-srt-plateau-break/state \
  --worktree-root /var/tmp/hssl-srt-plateau-break/worktrees \
  --task-prefix '## PLAT-' \
  --max-lanes 4 \
  --merge-target-branch benchmark/semantic-roundtrip-20260726 \
  --implement --start
```

Stop with `SIGTERM` or `Ctrl-C`. Do **not** use `bundle_supervisor --start --once`
as a dry run; use the scheduler `plan` command (or materializer
`--print-launch`) for inspection without leasing workers.

### Max lanes rationale

Foundation wave work (residual, packets, materializer, metrics, teachers) and
the four case edit waves (PLAT-081…084) are designed for limited parallelism.
**`max-lanes 4`** matches the case-parallel det. compiler wave width while
keeping CPU and merge-train pressure bounded. Raise only with explicit
operator approval and capacity receipts.

### Merge branch policy

- Default merge target: **`benchmark/semantic-roundtrip-20260726`**
  (or a successor plateau-break branch declared on the taskboard).
- Lane merges land on that branch only after the implementation daemon’s
  validation gate passes (packet `validation_commands` + structural checks).
- PLAT-090 owns the promotion decision for mean e2e / bootstrap CI; the
  materializer never auto-promotes production constructors.
- Do **not** rewrite the immutable 2026-07-27 replacement promotion report.

## Merge gate (post-materialization)

The daemon merges an implementable task only when:

1. Structural admission re-run still accepts the intended repair (or the
   deterministic code change is independently validated).
2. Packet-declared `validation_commands` pass.
3. Pilot re-score does not regress mean e2e above the pre-wave baseline
   (PLAT-090 owns the final promotion decision).

Obligation-only notes never satisfy the merge gate for candidate L1 or
production default changes.

## What the supervisor must not do

- Mark reject/timeout/error packets implementable.
- Expand `predicted_files` to optional runtime teachers (spaCy / Leanstral / AE)
  as production constructors.
- Claim semantic authority from Hammer/cvc5/Lean receipts.
- Silent-merge non-implementable packets.
- Rewrite the immutable 2026-07-27 replacement promotion report.

## Example

```python
from benchmarks.semantic_roundtrip.plateau_supervisor_materialize import (
    default_launch_spec,
    materialize_packet,
    materialize_packets,
)

# packet: sealed PlateauCodexPacket (implementable or not)
item = materialize_packet(packet)
assert item.semantic_authority is False
if item.implementable:
    assert item.predicted_files  # typed_deontic / realizer / tests only
    assert item.authorize_merge is False
else:
    assert item.kind.value == "obligation_only"
    assert item.predicted_files == ()

receipt = materialize_packets([packet])
print(receipt.merge_target_branch)  # benchmark/semantic-roundtrip-20260726
print(receipt.max_lanes)            # 4

spec = default_launch_spec()
assert "--max-lanes 4" in spec.to_command()
assert "benchmark/semantic-roundtrip-20260726" in spec.to_command()
```

## Related artifacts

- Packet contract: `docs/benchmarks/semantic_roundtrip_plateau_codex_packet.md`
- Taskboard: `docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md`
- Plan: `docs/benchmarks/semantic_roundtrip_plateau_break_plan.md`
- Dynamic supervisor runbook: `docs/implementation/runbooks/semantic_roundtrip_dynamic_supervisor.md`

## Downstream

- Edit waves: PLAT-081…084 (consume materializer tasks / packet digests)
- Re-measure + promotion: PLAT-090
