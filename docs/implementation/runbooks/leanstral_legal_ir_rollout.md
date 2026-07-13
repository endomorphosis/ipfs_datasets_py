# Leanstral LegalIR Rollout Runbook

This runbook controls promotion of Leanstral-assisted LegalIR compiler work from
shadow mode to broader production use.  Leanstral may propose bounded compiler
tasks, but deterministic compiler validation, graph checks, proof checks, and
anti-copy gates remain authoritative.

## Modes

- `off`: no Leanstral introspection, audit, TODO seeding, or enforcement.
- `export`: write introspection evidence only.
- `shadow`: audit evidence without seeding TODOs or mutating source.
- `seed`: append at most five verified real Leanstral TODOs for paired
  isolated implementation evaluation.
- `enforce`: fail closed when required Leanstral/introspection evidence is absent.

Default to `off`.  Use `enforce` only after the seed canary report permits
promotion and the active daemon configuration has explicit operator approval.

## Preflight

Run the shadow canary first:

```bash
PYTHONPATH=. python scripts/ops/legal_ir/run_leanstral_shadow_canary.py --dry-run --max-clusters 50
```

Real Lean checks default to full formula coverage, two-formula registry slices,
an adaptive worker count capped at eight, and a persistent local proof cache at
`workspace/leanstral-audit-worker/lean-proof-cache.json`. Cache entries bind the
canonical full and sliced IR hashes, theorem-generator source hash, and Lean
toolchain identity. Only successful Lean checks are reusable.

To restore the previous bounded proof behavior during rollback or diagnosis,
pass `--lean-max-formulas 2 --lean-slice-size 0 --lean-parallel-workers 1` and
use a separate `--lean-proof-cache-path`.

Run the seed canary without mutation:

```bash
PYTHONPATH=. python scripts/ops/legal_ir/run_leanstral_seed_canary.py --dry-run --max-todos 5 \
  --report-path docs/implementation/reports/leanstral_real_seed_canary.md
```

The seed report is written to
`docs/implementation/reports/leanstral_real_seed_canary.md`.

## Seed Evaluation

The seed canary must select no more than five tasks.  Each selected task must
have provenance evidence, anti-copy evidence, schema-valid packets, focused
allowed paths, theorem templates, mutation cases, validation commands, and a
matched non-Leanstral control task.  Production promotion evidence must include
actual isolated implementation outcomes for both the Leanstral and control arm.

The paired evaluation compares:

- compiler IR cross-entropy and cosine similarity
- learned LegalIR-view cross-entropy and cosine similarity
- proof validity and graph validity
- anti-copy penalty
- validation rejection rate
- task-to-accepted-patch rate
- cycle time
- state-to-accepted-patch lag
- accepted compiler/decompiler patch count
- autoencoder cycle overhead
- transient execution failure rate

## Promotion Rule

Permit broader rollout only when all of these are true:

- The canary is not a dry run.
- At most five locally verified real tasks were seeded.
- Every selected task has actual isolated Leanstral and control implementation
  evidence.
- At least one Leanstral compiler/decompiler patch was accepted.
- Task-to-accepted-patch rate improves by at least 20 percent against the
  matched control.
- State-to-accepted-patch lag is at least 25 percent lower than the matched
  control.
- Compiler IR CE/cosine and learned LegalIR-view CE/cosine do not regress on
  frozen holdouts.
- Theorem, graph, provenance, anti-copy, and mutation guardrails do not regress.
- Autoencoder cycle overhead is below 10 percent.
- Transient execution failure rate is below 5 percent.
- No hard guardrail regressed against the matched control.
- Every selected task has verified local evidence and, for production
  promotion, verified Leanstral audit evidence.

If any condition fails, keep the deployment at `shadow` or lower.

## Production Seed Command

Use this only after reviewing the dry-run report:

```bash
PYTHONPATH=. python scripts/ops/legal_ir/run_leanstral_seed_canary.py \
  --run-seed \
  --max-todos 5 \
  --input workspace/leanstral-shadow/disagreement_packets.jsonl \
  --cache-dir workspace/leanstral-audit-cache \
  --todo-queue-path workspace/leanstral-seed-canary/todos.jsonl \
  --report-path docs/implementation/reports/leanstral_real_seed_canary.md \
  --require-promotion
```

## Rollback

Rollback is mode-based and queue-based.  Disable Leanstral first, then remove
any unconsumed seed queue entries:

```bash
export LEANSTRAL_LEGAL_IR_MODE=off
pkill -f 'run_leanstral_seed_canary.py' || true
rm -f workspace/leanstral-seed-canary/todos.jsonl
PYTHONPATH=. python scripts/ops/legal_ir/run_leanstral_seed_canary.py --dry-run --max-todos 5 \
  --report-path docs/implementation/reports/leanstral_real_seed_canary.md
```

If the autoencoder daemon is running, restart it with introspection disabled:

```bash
export MODAL_INTROSPECTION_MODE=off
scripts/ops/logic/restart_autoencoder_codex_daemon.sh
```

Rollback is mandatory when compiler IR CE/cosine, learned IR-view metrics,
proof or graph validity, anti-copy penalty, validation rejection rate,
task-to-accepted-patch rate, cycle time, state-to-accepted-patch lag,
autoencoder cycle overhead, transient execution failure rate, provenance, or
mutation guardrails regress.
