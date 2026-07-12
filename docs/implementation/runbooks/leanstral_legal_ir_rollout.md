# Leanstral LegalIR Rollout Runbook

This runbook controls promotion of Leanstral-assisted LegalIR compiler work from
shadow mode to broader production use.  Leanstral may propose bounded compiler
tasks, but deterministic compiler validation, graph checks, proof checks, and
anti-copy gates remain authoritative.

## Modes

- `off`: no Leanstral introspection, audit, TODO seeding, or enforcement.
- `export`: write introspection evidence only.
- `shadow`: audit evidence without seeding TODOs or mutating source.
- `seed`: append at most five verified Leanstral TODOs for paired evaluation.
- `enforce`: fail closed when required Leanstral/introspection evidence is absent.

Default to `off`.  Use `enforce` only after the seed canary report permits
promotion and the active daemon configuration has explicit operator approval.

## Preflight

Run the shadow canary first:

```bash
PYTHONPATH=. python scripts/ops/legal_ir/run_leanstral_shadow_canary.py --dry-run --max-clusters 50
```

Run the seed canary without mutation:

```bash
PYTHONPATH=. python scripts/ops/legal_ir/run_leanstral_seed_canary.py --dry-run --max-todos 5
```

The seed report is written to
`docs/implementation/reports/leanstral_seed_canary.md`.

## Seed Evaluation

The seed canary must select no more than five tasks.  Each selected task must
have provenance evidence, anti-copy evidence, schema-valid packets, focused
allowed paths, theorem templates, mutation cases, validation commands, and a
matched non-Leanstral control task.

The paired evaluation compares:

- compiler IR cross-entropy and cosine similarity
- learned LegalIR-view cross-entropy and cosine similarity
- proof validity and graph validity
- anti-copy penalty
- validation rejection rate
- task-to-accepted-patch rate
- cycle time
- state-to-patch lag

## Promotion Rule

Permit broader rollout only when all of these are true:

- The canary is not a dry run.
- At most five verified tasks were seeded.
- No hard guardrail regressed against the matched control.
- Compiler development throughput materially improved by the configured
  threshold.
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
  --report-path docs/implementation/reports/leanstral_seed_canary.md \
  --require-promotion
```

## Rollback

Rollback is mode-based and queue-based.  Disable Leanstral first, then remove
any unconsumed seed queue entries:

```bash
export LEANSTRAL_LEGAL_IR_MODE=off
pkill -f 'run_leanstral_seed_canary.py' || true
rm -f workspace/leanstral-seed-canary/todos.jsonl
PYTHONPATH=. python scripts/ops/legal_ir/run_leanstral_seed_canary.py --dry-run --max-todos 5
```

If the autoencoder daemon is running, restart it with introspection disabled:

```bash
export MODAL_INTROSPECTION_MODE=off
scripts/ops/logic/restart_autoencoder_codex_daemon.sh
```

Rollback is mandatory when compiler IR CE/cosine, learned IR-view metrics,
proof or graph validity, anti-copy penalty, validation rejection rate,
task-to-accepted-patch rate, cycle time, or state-to-patch lag regresses.
