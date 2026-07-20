# Legal IR Hammer Leanstral Operator Runbook

This runbook covers the hammer/Leanstral path for the legal text compiler optimizer. The goal is to improve the deterministic compiler/decompiler and the learned LegalIR view without treating unverified model text as ground truth.

## Stop Active Runs

Stop any existing legal-IR daemon before changing rollout settings:

```bash
pkill -TERM -f 'legal-ir|uscode_modal|run_leanstral|logic_theorem_optimizer|modal_autoencoder' || true
pgrep -af 'legal-ir|uscode_modal|run_leanstral|logic_theorem_optimizer|modal_autoencoder' || true
```

Only the `pgrep` command itself should remain.

## Supervisor Handoff

The taskboard is parseable by the `ipfs_accelerate_py` implementation daemon:

Use the repository-local lifecycle wrapper for normal operation:

```bash
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh status
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh once
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh start
scripts/ops/legal_ir/hammer_leanstral_supervisor.sh stop
```

`start` deliberately refuses a dirty checkout. Ephemeral implementation
worktrees are created from `HEAD`, so completed prerequisite work must be
committed before the remaining tasks are dispatched.

```bash
PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. \
  .venv-cuda/bin/python -m ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon \
  --todo docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md \
  --task-prefix '## PORTAL-'
```

Keep legal-IR-specific logic in `ipfs_datasets_py`. Keep general daemon, routing, and worker management improvements in `ipfs_accelerate_py`.

## Smoke Run

Run one guarded hammer/Leanstral autoencoder/Codex cycle:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh
```

Dry-run the exact command:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh --dry-run
```

Gate an existing summary:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh \
  --gate-only \
  --summary-path workspace/test-logs/<run-id>-autoencoder.summary
```

## Hparam Then 24h Run

Run a 1-hour hyperparameter sweep followed by a 24-hour optimizer loop:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh
```

The default sweep is six 10-minute trials. The final optimizer run is 24 hours. Override these with environment variables:

```bash
TRIAL_SECONDS=600 \
TRIAL_COUNT=6 \
FINAL_SECONDS=86400 \
CODEX_SCOPE_WORKERS=2 \
scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh
```

The script delegates to `scripts/ops/logic/run_hparam_then_8h.sh` with hammer/Leanstral extra daemon arguments and changes the final run label to `24h`.

## Metrics

Primary quality metrics:

- `best_validation_ce` and `latest_validation_ce`: learned autoencoder cross entropy.
- `best_validation_cosine` and `latest_validation_cosine`: learned embedding similarity.
- `best_validation_ir_ce` and `latest_compiler_ir_ce`: deterministic compiler/decompiler IR cross entropy.
- `best_validation_ir_cosine` and `latest_compiler_ir_cosine`: deterministic compiler/decompiler IR cosine.
- `hammer_proof_success_rate`: fraction of hammer guidance obligations proved.
- `hammer_reconstruction_success_rate`: fraction reconstructed into trusted native proof form.
- `trusted_hammer_guidance_count`: guidance records allowed to train the autoencoder.
- `latest_compiler_ir_source_copy_reward_hack_penalty`: penalty for source-copy style reward hacking.

Leanstral drafts are guidance only. A draft becomes trusted training signal only after deterministic syntax, provenance, knowledge graph, hammer, or reconstruction checks accept it.

## Rollout Gate

The shared gate is:

```bash
.venv-cuda/bin/python -m scripts.ops.legal_ir.hammer_leanstral_rollout_gate gate \
  --summary-path workspace/test-logs/<run-id>-autoencoder.summary
```

It rejects:

- validation CE/cosine regressions beyond configured tolerances,
- compiler IR CE/cosine regressions beyond configured tolerances,
- excessive source-copy penalties,
- missing hammer cycle telemetry,
- stalled TODO generation after at least one cycle,
- failed child process exits or fatal backend availability failures.

Unavailable solvers are allowed when reported as degraded backend health. They become fatal only if the operator sets `--require-available-hammer-backend`.

## Parallelism Knobs

Use these environment variables for CPU utilization:

- `CODEX_PARALLEL_SCOPES`: comma-separated AST scopes or `all`.
- `CODEX_SCOPE_WORKERS`: Codex workers per scope.
- `AUTOENCODER_BRIDGE_WORKERS`: bridge/prover evaluation workers.
- `DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS`: hammer backend worker count.
- `LEANSTRAL_AUDIT_BATCH_SIZE` and `LEANSTRAL_AUDIT_BATCH_USE_MESH`: Leanstral batch and p2p mesh settings.

Raise Codex workers until validation failures or main-apply contention increase. Raise hammer/bridge workers only when bridge/prover phases dominate cycle time.
