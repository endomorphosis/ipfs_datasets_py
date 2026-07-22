# LegalIR Ten-Minute Integrated Smoke Report

- Task: `PORTAL-LIR-HAMMER-117`
- Stage: `ten_minute_smoke`
- Policy: fail closed
- Evidence: `docs/implementation/reports/evidence/legal_ir_10_minute_integrated_smoke.json`
- Verifier: `scripts/ops/legal_ir/verify_legal_ir_run_evidence.py`

## Decision

The committed compact receipt is the authoritative decision input. It is
accepted only when the verifier recomputes every runtime, lineage, service,
quality, timing, storage, and cleanup check with no failures. A successful
daemon exit, dry-run, fixture replay, or a legacy task-116 stage fragment is not
accepted as execution evidence.

The first execution attempt in this task is intentionally excluded from the
accepted lineage. Its autoencoder completed two cycles and recorded 750.155
seconds, but the outer shell was modified while the long-lived interpreter was
still reading it; the post-run launcher failed and the system-Python process
also reported `python_cuda_unavailable`. Those artifacts are retained only in
the transient operator workspace as rejected evidence. No duration, metric, or
service claim from that attempt is combined with the accepted run.

## Executed Contract

`scripts/ops/legal_ir/run_legal_ir_10m_smoke.sh` is the task-specific entry
point. It wraps the canonical paired runner in a dedicated process group and an
outer heartbeat watchdog. The stage duration cannot be lowered below 600 active
seconds through an argument or environment override. It refuses overwrites,
requires CUDA for both the autoencoder and Leanstral, preserves run-local bulky
artifacts outside Git, terminates the process group on timeout or signal, and
seals a receipt only after canonical cleanup succeeds.

The selected fixed configuration is recorded in full in the receipt and bound
to its SHA-256. It uses the deterministic sampling seed
`PORTAL-LIR-HAMMER-117-fixed-smoke-v1`, the fixed validation canary, one
canonical CUDA trainer, one persistent CUDA Leanstral generation, bounded
Hammer reconstruction, bounded Codex `patch_only` work, serialized main apply,
and atomic bounded persistence. Task 115 did not commit a winning-candidate
artifact, so this report does not falsely attribute the smoke configuration to
an unavailable hparam winner.

## Independent Verification

The verifier rejects rather than trusts headline booleans. It recomputes:

- canonical manifest SHA-256, exact stage/run/configuration/fixture/state
  bindings, timezone-aware timestamp order, non-overlapping active intervals,
  and resume lineage;
- at least 600 active seconds, at least two completed warm cycles, advancing
  sample counters, and distinct initial/final state revisions;
- real `torch_cuda` forward, finite loss, backward, and optimizer-step counts,
  with simulation and CPU fallback explicitly false;
- one healthy CUDA Leanstral service generation, one load and preflight, stable
  model/context fingerprint, warm reuse, and queue/inference/verification timing;
- Hammer obligations, backend attempts, proof attempts, and reconstruction;
- a bounded fixed-fixture Codex TODO, invocation, focused validation, and either
  an accepted merge or an explicitly reasoned safe rejection;
- exact seven-family coverage and finite baseline/candidate IR and autoencoder
  CE/cosine, semantic, proof, reconstruction, provenance, round-trip,
  uncertainty, holdout, and anti-copy metrics with direction-aware
  non-regression;
- bounded stage/queue timings, durable content-addressed artifacts, clean
  watchdog exit, equal launched/reaped child counts, and zero orphaned children
  or concurrent canonical writers.

The receipt is compact by design. It contains hashes, sizes, counters, metric
values, identities, and sanitized Codex dispositions, but no checkpoint tensor
payload, model weights, legal-source prompt, raw Codex prompt, or patch body.
Optional local-artifact verification rehashes any still-available run files;
normal committed verification remains possible after transient workspaces are
cleaned.

## Reproduction

Execute a fresh immutable lineage:

```bash
scripts/ops/legal_ir/run_legal_ir_10m_smoke.sh \
  --run-id legal-ir-10m-smoke-YYYYMMDDTHHMMSSZ
```

Verify the committed receipt independently:

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python \
  scripts/ops/legal_ir/verify_legal_ir_run_evidence.py \
  --evidence docs/implementation/reports/evidence/legal_ir_10_minute_integrated_smoke.json \
  --stage ten_minute_smoke \
  --minimum-active-seconds 600
```

`--dry-run` prints the immutable command contract and explicitly states
`execution=false` and `promotable_evidence=false`; it cannot create or replace
the committed receipt.
