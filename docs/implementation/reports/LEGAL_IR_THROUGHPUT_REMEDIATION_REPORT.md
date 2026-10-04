# LegalIR Throughput Remediation Promotion Report

- Task: `PORTAL-LIR-HAMMER-116`
- Track: rollout
- Gate schema: `legal-ir-throughput-remediation-rollout-v1`
- Gate command: `scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py throughput-remediation-gate`
- Policy: fail closed
- Scope: benchmark and staged-rollout definitions; not a record of a completed production run

## Current Decision

**Not promoted.** This change defines the reproducible benchmark, integrated
runner, evidence schema, and promotion gate. It does not claim that the
ten-minute, one-hour, eight-hour, or twenty-four-hour runs have happened. A
dry-run is synthetic contract-validation output and is never execution or
promotion evidence. Until fresh, complete evidence for every stage is supplied
to the gate, the decision remains failed.

Execution evidence is deliberately assigned to the follow-on rollout tasks.
In particular, `PORTAL-LIR-HAMMER-117` must execute and verify the ten-minute
smoke; a successful unit test or `--dry-run` here cannot satisfy that task.

## Implemented Artifacts

| Artifact | Operational purpose |
| --- | --- |
| `benchmarks/bench_legal_ir_optimizer_pipeline.py` | Produces content-addressed, matched cold/warm baseline and candidate benchmark evidence. Its dry-run checks only the output contract. |
| `scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh` | Starts the canonical supervised CUDA autoencoder, persistent CUDA Leanstral, Hammer, and Codex paths and verifies their integrated summaries. |
| `scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py` | Recomputes the throughput and quality decision from persisted evidence; missing evidence is a blocker. |
| `tests/unit/optimizers/logic_theorem_optimizer/test_throughput_remediation_rollout.py` | Exercises successful evidence and fail-closed omissions, regressions, lineage mismatches, process leaks, and resource-bound failures. |

The Python interface is `throughput_remediation_rollout_gate(payload,
config=None)`. `ThroughputRemediationConfig` owns operator-adjustable resource
limits and hard thresholds; `THROUGHPUT_REMEDIATION_STAGES` is the canonical
stage order. `render_throughput_remediation_report` renders a persisted decision
without weakening it.

## Stage Contract

Stages are ordered and lineage-bound. A later stage cannot compensate for a
missing or failed earlier stage.

| Stage | Required active duration | Required output |
| --- | ---: | --- |
| `matched_benchmark` | not timed (`0`) | Complete cold and warm trials. Baseline and candidate use the same revision-independent workload, split, seed set, hardware identity, model/context identity, and measurement window. Both cache states and all required metric families must be present. |
| `ten_minute_smoke` | 600 seconds | Complete supervised-stack evidence, at least the configured warm-cycle minimum, durable summary/checkpoint, cleanup evidence, and a gate decision. |
| `one_hour_hparam` | 3,600 seconds | Resource-aware search evidence bound to the benchmark baseline and immutable compiler artifacts, including the selected configuration and rejected trials. |
| `eight_hour_canary` | 28,800 seconds | The selected configuration, matched time series, checkpoint/resume drill, rollback point, service health, resource bounds, and all hard quality gates. |
| `twenty_four_hour_production` | 86,400 seconds | Continuous production-stage evidence, final durable checkpoint, tested rollback metadata, bounded artifacts, clean process shutdown, and all preceding stage bindings. |

Only lineage-verified active runtime counts. Startup, downtime, dry-runs,
fixture replay, validation-only work, and a stopped interval between a
checkpoint and resume do not count toward stage duration. Every snapshot must
identify the stage, rollout and run IDs, code revision, baseline and candidate
configuration digests, workload/split/seed identity, host/GPU identity,
start/end timestamps, accumulated active seconds, evidence schema, and content
digest. Stale, simulated, incomplete, non-finite, unsupported-schema, or
lineage-mismatched snapshots fail.

The smoke contract can be inspected without launching services:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh --dry-run
```

A real execution uses a fresh destination ID and explicit evidence locations:

```bash
scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh \
  --run-id legal-ir-smoke-YYYYMMDDTHHMMSSZ \
  --evidence-output workspace/test-logs/legal-ir-smoke-evidence.json \
  --rollback-artifact workspace/test-logs/legal-ir-smoke-rollback.json
```

That command is intentionally duration-bound to 600 seconds. To validate
already-created artifacts, use `--gate-only`; to resume generalizable state
into a new immutable run lineage, use `--resume-from-run-id OLD_ID` or
`--resume-from-state PATH`, never both. Merely printing either command is not a
completed stage.

## Reproducible Matched Benchmark

The benchmark is an aggregator of real pipeline summaries, not a substitute
microbenchmark. For each profile, run a cold trial against a newly initialized
designated benchmark cache, then a warm trial that retains that exact cache.
Do not delete shared caches or change the fixture, seed, worker profile, model,
context size, compiler artifacts, CUDA device, or quality thresholds between
the matched baseline and candidate. Record cache state explicitly and retain
the raw input digests.

An operator may aggregate persisted summaries as follows:

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python \
  benchmarks/bench_legal_ir_optimizer_pipeline.py \
  --input workspace/legal_ir/benchmark/baseline-cold.json \
  --input workspace/legal_ir/benchmark/baseline-warm.json \
  --input workspace/legal_ir/benchmark/candidate-cold.json \
  --input workspace/legal_ir/benchmark/candidate-warm.json \
  --output workspace/legal_ir/benchmark/matched-report.json
```

The installation check is intentionally non-promotable:

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python \
  benchmarks/bench_legal_ir_optimizer_pipeline.py --dry-run
```

The resulting matched evidence must expose raw counts and elapsed active time,
not only precomputed ratios. This lets the gate recompute cycles/hour,
samples/second, and p95 lag and reject zero-duration, non-finite, or
denominator-mismatched comparisons.

## Hard Promotion Requirements

Promotion requires every check below. There are no warning-only substitutes.

### Runtime authenticity and service health

- Autoencoder evidence proves CUDA forward, loss, backward, and optimizer
  updates; the declared device is CUDA and CPU fallback is false.
- Leanstral evidence proves one healthy CUDA service generation survives
  warmup, the canonical weights load once, compatible requests reuse that
  generation, and model/context identity remains fixed.
- Hammer evidence includes obligations, an available backend, proof attempts,
  and reconstruction activity. A headline `healthy` value without counters is
  insufficient.
- Codex evidence includes bounded TODO/queue activity, an invocation, focused
  validation, and an accepted patch or safe rejection. Queue lineage must match
  the supervised run.
- Watchdog and managed-process evidence accounts for every child. At stage
  close, no child may be alive, unknown, stale, leaked, or orphaned, and no
  canonical concurrent writer may remain.

### Throughput, lag, and storage

Relative comparisons are made only against the matched warm baseline:

- candidate warm cycles/hour divided by baseline warm cycles/hour is at least
  `1.8`;
- candidate samples/second divided by baseline samples/second is at least
  `1.5`;
- candidate p95 state-to-accepted-patch lag is strictly lower than baseline;
- checkpoint bytes and summary bytes are finite, non-negative, and no greater
  than the limits declared by the gate policy (defaults: 512 MiB per
  checkpoint and 16 MiB per summary); and
- queue, memory, and process telemetry required by the stage is present and
  within its configured bound.

The accepted-patch lag is based on accepted, lineage-matched patches. Generated
diffs, unvalidated patches, safe rejections, and validation failures cannot be
relabelled as accepted patches to improve throughput or lag.

### Quality non-regression

Baseline and candidate must include the same complete LegalIR family set.
Every required family is checked independently; averaging cannot hide one bad
family. For every family, promotion requires non-regression in:

- IR and autoencoder cross-entropy;
- IR and autoencoder cosine;
- semantic equivalence and symbolic validity;
- Hammer proof success and proof reconstruction;
- provenance preservation and source traceability;
- compiler/decompiler round trip;
- uncertainty/calibration behavior;
- frozen-holdout behavior; and
- source-copy/anti-copy behavior.

Direction is metric-specific: loss, error, lag, uncertainty error, and
source-copy penalties must not increase; cosine, equivalence, validity, proof,
reconstruction, provenance, round-trip, and holdout scores must not decrease.
All values must be finite and derived from the same fixed evaluation material.
Missing families, missing metric keys, changed family sets, changed holdouts,
or a single regression block promotion even when aggregate quality improves.

## Resume Evidence

A resumed stage must preserve one unbroken evidence lineage. Each resume record
must bind the prior and restored checkpoint digests, configuration and code
revision, model/context identity, last committed state revision, sample and
cycle counters, accumulated active seconds before and after restore, reason,
timestamps, and successful post-restore health check. Counters must be
monotonic, active intervals must not overlap, and downtime must not be counted.
The checkpoint size and digest must be checked before resuming. An absent
resume record is acceptable only when the stage reports zero resumes; claiming
a resume without the complete record fails the stage.

## Rollback Evidence

Every stage must establish a rollback point before it can promote. Evidence
includes a rollback ID, the previous configuration/artifact identity, a
content-addressed checkpoint or immutable restore target, its byte size, and a
concrete disable or restore action. The action must be recorded as verified (or
the artifact must be verified when artifact verification is enabled), must not
point outside the declared rollout lineage, and must restore a configuration
that previously passed its applicable gate. Missing, unreadable,
digest-mismatched, oversized, already-required, or non-restorable rollback
evidence blocks promotion.

On a hard failure, operators stop admission of new work, preserve the failed
evidence envelope, terminate the supervised process group, verify zero
orphaned children, execute the recorded rollback action, restore the previous
checkpoint/configuration, and re-run that previous stage's gate. Failed stage
runtime is never carried forward into a replacement run.

## Ablation Attribution

The committed attribution ledger is deliberately explicit about the absence of
execution measurements:

| Remediation arm | Warm cycles/hour gain | Samples/second gain | p95 lag change | Evidence status |
| --- | ---: | ---: | ---: | --- |
| CUDA autoencoder training | not measured | not measured | not measured | blocking |
| Persistent CUDA Leanstral reuse | not measured | not measured | not measured | blocking |
| Hammer/proof and reconstruction parallelism | not measured | not measured | not measured | blocking |
| Compiler/evaluation caching and stage scheduling | not measured | not measured | not measured | blocking |
| Codex bundle and incremental-validation rescue | not measured | not measured | not measured | blocking |
| Resource-aware hparam scheduling | not measured | not measured | not measured | blocking |

This ledger attributes no gain to any arm. It can be replaced only by matched
one-change-at-a-time evidence; until then, incomplete ablation attribution is a
promotion failure.

The report format requires a baseline plus one evidence packet for each enabled
remediation component. Each packet uses the same warm workload and measurement
contract and records the component name and version, baseline and ablated
configuration digests, raw cycle/sample/lag measurements, derived deltas, the
full quality matrix, and its evidence digest. Examples of components that must
be separated when enabled are persistent Leanstral reuse, CUDA autoencoder
training, Hammer/proof parallelism, compiler/evaluation caching, Codex bundle
and incremental validation, and hparam scheduling.

Gains are attributed from measured ablations, never inferred from the final
headline speedup. If components interact, report the ordered incremental
comparison and an interaction/residual term; do not assign the same gain to
multiple components. An ablation that changes fixtures, hardware, seeds,
quality thresholds, stage duration, or family coverage is unmatched and
invalid. Every ablation must preserve the full quality gate. A missing required
ablation, failed ablation guardrail, or sum that cannot be reconciled to the
observed candidate result blocks promotion.

No measured gains are published in this implementation report because no real
matched rollout evidence accompanies this task. The deterministic dry-run
numbers are examples for schema validation and must not be copied into an
ablation or promotion decision.

| Ablation component | Matched measurement in this task | Attributed gain | Promotion effect |
| --- | --- | --- | --- |
| persistent CUDA Leanstral reuse | not executed | not claimed | required evidence absent |
| CUDA autoencoder training path | not executed | not claimed | required evidence absent |
| Hammer/proof parallelism | not executed | not claimed | required evidence absent |
| compiler/evaluation caching | not executed | not claimed | required evidence absent |
| Codex bundling/incremental validation | not executed | not claimed | required evidence absent |
| resource-aware hparam scheduling | not executed | not claimed | required evidence absent |

This ledger is the only honest attribution available at definition time: no
component receives credit, and promotion stays failed. A real decision report
replaces each applicable row with content-addressed matched measurements and
retains `not applicable` rows only for components demonstrably disabled in
both baseline and candidate.

## Fail-Closed Decision Semantics

The gate recomputes a decision from evidence and emits a structured failure for
every unmet requirement. It never trusts a supplied `accepted`, `passed`, or
`healthy` headline on its own. Unknown schema versions and unknown metric
families are blockers. Empty lists do not prove activity. A missing boolean is
not false evidence and a missing counter is not zero evidence: both are absent
evidence and therefore fail.

Gate output must be persisted atomically and content-addressed. Exit status
`0` means that the complete supplied rollout envelope passed. Any missing
stage, evidence packet, threshold, binding, resume/rollback record, ablation,
or cleanup receipt produces a non-zero exit and leaves production promotion
disabled.

An operator evaluates a complete evidence envelope with:

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python \
  scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py \
  throughput-remediation-gate \
  --evidence-path workspace/legal_ir/throughput-remediation-evidence.json \
  --evidence-output workspace/legal_ir/throughput-remediation-decision.json \
  --report-output workspace/legal_ir/throughput-remediation-decision.md
```

The committed report is not used as evidence input. Generated decision reports
belong beside their evidence envelope so their digest and lineage can be
audited together.

## Validation

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest \
  tests/unit/optimizers/logic_theorem_optimizer/test_throughput_remediation_rollout.py \
  tests/unit/optimizers/logic_theorem_optimizer/test_evidence_driven_rollout.py \
  tests/unit/optimizers/logic_theorem_optimizer/test_compiler_system_promotion_gate.py -q

/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python \
  benchmarks/bench_legal_ir_optimizer_pipeline.py --dry-run
```

These commands validate implementation and schema behavior. They do not change
the current decision above and do not constitute ten-minute, canary, or
production execution evidence.
