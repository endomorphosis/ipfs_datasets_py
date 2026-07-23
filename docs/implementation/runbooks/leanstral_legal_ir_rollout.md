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

## Local DGX Spark Leanstral

Use `ipfs_accelerate_py` as the single owner of llama.cpp installation,
updates, server startup, and OpenAI-compatible routing.  `ipfs_datasets_py`
should select the provider only; it should not shell out to llama.cpp directly.

Preflight without installing or starting anything:

```bash
cd ../ipfs_accelerate_py
PYTHONPATH=. python -m ipfs_accelerate_py.utils.llama_cpp --probe
PYTHONPATH=. python -m ipfs_accelerate_py.utils.llama_cpp \
  --model-status \
  --model-ref Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4 \
  --hf-file Leanstral-1.5-119B-A6B-NVFP4.gguf
```

Install or update the llama.cpp CLI and prefetch the exact GGUF only with
explicit operator approval:

```bash
cd ../ipfs_accelerate_py
PYTHONPATH=. python -m ipfs_accelerate_py.utils.llama_cpp \
  --prefetch-model \
  --model-ref Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4 \
  --hf-file Leanstral-1.5-119B-A6B-NVFP4.gguf

PYTHONPATH=. python -m ipfs_accelerate_py.utils.llama_cpp \
  --serve \
  --auto-install \
  --auto-update \
  --model-ref Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4 \
  --hf-file Leanstral-1.5-119B-A6B-NVFP4.gguf \
  --context-size 2048 \
  --startup-timeout-seconds 1800
```

Point the Leanstral audit worker at the local server:

```bash
export LEANSTRAL_AUDIT_PROVIDER=leanstral_local
export LEANSTRAL_AUDIT_MODEL=Leanstral
export IPFS_ACCELERATE_LLAMA_CPP_BASE_URL=http://127.0.0.1:8080/v1
export IPFS_ACCELERATE_LLAMA_CPP_MODEL_REF=Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4
export IPFS_ACCELERATE_LLAMA_CPP_HF_FILE=Leanstral-1.5-119B-A6B-NVFP4.gguf
export LEANSTRAL_AUDIT_REFERENCE_EXAMPLE_PATHS=workspace/todo-queues/legal-ir-autoencoder-canonical.state.json
```

Use `IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART=1` only when the daemon should start a
missing local server.  Use `IPFS_ACCELERATE_LLAMA_CPP_AUTO_INSTALL=1` and
`IPFS_ACCELERATE_LLAMA_CPP_AUTO_UPDATE=1` only in an installation/update window,
not as default production daemon settings.  Use
`IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL=1` only when the daemon is allowed to
resume or create the model download before serving.

Optional distributed audit artifact cache:

```bash
export IPFS_DATASETS_PY_LEANSTRAL_ARTIFACT_CACHE=1
export IPFS_DATASETS_PY_LEANSTRAL_ARTIFACT_INDEX_PATH=workspace/leanstral-audit-cache/.leanstral-artifact-cache-index.json
export IPFS_DATASETS_PY_LEANSTRAL_ARTIFACT_PIN=1
export ENABLE_IPFS_KIT=true
export IPFS_KIT_CACHE_DIR=workspace/ipfs-kit-cache
```

The local JSON cache remains authoritative.  When enabled, verified Leanstral
audit cache entries are also written through the `ipfs_accelerate_py` storage
wrapper, which prefers `ipfs_kit_py` and falls back according to its configured
backend policy.  Distributed-cache misses or backend failures must not block
local cache writes, audit validation, or daemon progress.

Fast local smoke from `ipfs_datasets_py`:

```bash
PYTHONPATH=../ipfs_accelerate_py:. \
IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART=1 \
IPFS_ACCELERATE_LLAMA_CPP_AUTO_INSTALL=1 \
IPFS_ACCELERATE_LLAMA_CPP_HF_FILE=Leanstral-1.5-119B-A6B-NVFP4.gguf \
IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL=1 \
IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS=1800 \
python scripts/ops/legal_ir/run_leanstral_shadow_canary.py \
  --input latest \
  --max-records 1 \
  --max-clusters 1 \
  --min-real-packets 1 \
  --run-provider \
  --provider leanstral_local \
  --model Leanstral \
  --vibe-agent lean \
  --max-concurrency 1 \
  --max-retries 0 \
  --timeout-seconds 300
```

The production daemon writes canonical disagreement packets as
`workspace/test-logs/<run-id>.canonical-disagreements.jsonl` and local verifier
reference examples as `workspace/test-logs/<run-id>.reference-examples.json`.
The audit companion also recognizes the older `-autoencoder` filenames for
rollback compatibility.  Use `--input latest` in the shadow or seed canary to
consume the newest canonical disagreement export that meets the canary's
minimum packet count, which prevents a short smoke export from hiding an older
production-sized export.

Real shadow canaries treat canonical disagreement exports as append-only logs.
They validate the export, group valid packets by `(state_hash, compiler_commit)`,
and audit one coherent snapshot rather than mixing historical compiler states.
The report's `canonical_state.snapshot_selection` section shows which snapshot
was selected and how many valid packets were dropped as historical context.  If
the latest snapshot has fewer packets than `--min-real-packets`, the canary must
block with `insufficient_real_canonical_packets`; lower that threshold only for
explicit smoke checks.

The cache-only real shadow canary defaults to the same request-key policy as the
production audit watcher: `--evidence-refresh-policy latest_compiler_snapshot`
and `--max-evidence-packets-per-item 1`.  Use `--evidence-refresh-policy
full_manifest` only when intentionally checking strict append-only attestation;
it will not reuse production watcher cache entries.

The asynchronous audit worker uses the same snapshot rule by default through
`--snapshot-selection latest_canonical_snapshot`.  The watcher exposes this as
`LEANSTRAL_AUDIT_SNAPSHOT_SELECTION` and reports the selected snapshot in the
worker JSON summary.  A latest snapshot below `LEANSTRAL_AUDIT_MIN_SNAPSHOT_RECORDS`
is still audited, but the summary marks `meets_min_snapshot_records: false` so
the autoencoder export-volume gap remains visible.

Production canonical autoencoder runs should emit at least 25 real packets per
coherent compiler snapshot.  Keep `VALIDATION_CANARY_COUNT` and
`AUTOENCODER_INTROSPECTION_MIN_EXPORT_SAMPLES` at 25 or higher for production
Leanstral evidence.  `AUTOENCODER_MAX_AUDITS_PER_CYCLE` can stay lower because
it bounds Codex TODO/audit work, not the packet-export evidence floor.

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
