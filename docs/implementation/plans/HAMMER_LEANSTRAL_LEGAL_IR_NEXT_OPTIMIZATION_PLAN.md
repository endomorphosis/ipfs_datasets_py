# Hammer/Leanstral LegalIR Next Optimization Plan

## Purpose

The legal compiler loop should use learned representations to discover recurring
semantic gaps, Leanstral to turn difficult gaps into typed hypotheses, Hammer and
deterministic validators to decide which hypotheses are trustworthy, and Codex to
implement verified gaps as deterministic compiler/decompiler rules.

The production authority chain is:

`legal text -> deterministic multi-view LegalIR -> learned LegalIR view -> typed obligations -> Leanstral hypotheses -> Hammer/local verification -> bounded Codex TODO -> isolated patch validation -> deterministic compiler promotion`

Neither Leanstral text nor autoencoder weights are production legal semantics.
The deterministic compiler remains authoritative; learned behavior reaches it
only through evidence-bound, reversible, tested rule changes.

## Observed Baseline

The integrated CUDA smoke proved that the autoencoder, Hammer, Leanstral, and
Codex can participate in one queue lineage. The six-trial search then exposed
quality and runtime gaps that the completed foundation tasks do not yet resolve:

- all six trials reported the same compiler IR CE (`2.572561757`) and cosine
  (`0.052416487`) despite materially different autoencoder hyperparameters;
- validation CE improved to `0.931838101`, but the fixed compiler IR metrics do
  not establish that the learned representation improved compiler behavior;
- the smoke lacked a representation-promotion report;
- three cycles spent about 402 seconds in projection training, 86 seconds in
  validation, 82 seconds in embeddings, 63 seconds in compilation, 32 seconds
  in disagreement export, and 21 seconds in state persistence;
- useful CPU utilization averaged about 7.5 percent, while work remained mostly
  serialized;
- runtime telemetry reported the GPU unavailable even though CUDA processes were
  observed, so resource autotuning cannot yet trust its GPU inputs;
- the metric cache hit rate was about 82.5 percent, leaving room for a shared
  immutable artifact graph and single-flight coalescing;
- sequential full-budget hyperparameter trials spend scarce CUDA time on weak
  candidates instead of using early stopping and asynchronous evaluation.

## Authority And Responsibilities

### Hammer

Use Hammer as the trust-producing lane for:

1. Per-family well-formedness and semantic obligations for deontic, frame logic,
   TDFOL, knowledge graphs, CEC, temporal, provenance, external-prover, and
   decompiler views.
2. Cross-view invariants such as actor/action/object identity, exception
   precedence, prohibition polarity, temporal consistency, graph typing, and
   provenance preservation.
3. Text/IR and IR/text/IR round-trip obligations that reward semantic structure
   without rewarding source copying.
4. Cheap-first counterexample search, premise selection, solver portfolios, and
   kernel/native reconstruction.
5. Negative supervision from minimal failed contracts and verified
   counterexamples.
6. Changed-scope validation for Codex patches and the full frozen proof set at
   merge and rollout boundaries.

Hammer receipts must bind the obligation, premises, translation/toolchain
versions, resource policy, outcome, reconstruction status, and evidence hashes.

### Leanstral

Use Leanstral as a bounded reasoning lane for:

1. Auditing high-impact or recurrent learned/compiler disagreements.
2. Decomposing broad failed obligations into minimal typed subgoals.
3. Explaining which semantic slot, view contract, premise family, or compiler
   surface is missing.
4. Suggesting typed rule candidates, counterexamples, mutation cases, and
   verifier-owned proof bodies.
5. Classifying failed Codex validations as semantic, stale, unsupported, or
   operational.

Do not invoke Leanstral for cache hits, already-solved obligations, low-impact
noise, or gaps lacking owned compiler surfaces. Its output remains untrusted
until syntax, provenance, anti-copy, deterministic contract, Hammer, and any
required reconstruction checks pass.

### Autoencoder

Use the autoencoder to predict semantic slots, LegalIR view families,
proof-obligation families, premise families, proof-route availability,
reconstruction outcomes, and decompiler plans. Train only from source-free,
version-matched compiler targets and trusted proof-feedback records.

The learned and deterministic paths must be measured separately:

- `learned_ir_*`: trainable compiler-facing representation quality;
- `deterministic_compiler_ir_*`: behavior of the current compiler;
- `learned_to_compiler_disagreement_*`: actionable transfer gap;
- `promotion_*`: whether a learned pattern passed causal, canary, and rollback
  requirements and became deterministic behavior.

### Codex

Use Codex only after a recurring or formally serious gap has a verified evidence
packet. Each task must own one AST/compiler scope, identify allowed paths,
include positive and negative examples, name exact target metrics and proof
obligations, and carry focused plus frozen validation commands. Concurrent work
is allowed across predicted-disjoint write sets; overlapping merges remain
serialized.

## Target Runtime Architecture

Keep one canonical CUDA trainer. It publishes immutable, versioned snapshots to
a bounded evaluation queue while continuing training. CPU evaluators shard a
matching snapshot by LegalIR family and reuse one typed compilation/embedding
artifact graph. Hammer workers consume independent obligations under a global
child-process and memory lease. A persistent CUDA Leanstral service continuously
batches selected audits. Codex workers consume verified TODOs by disjoint scope,
validation workers run isolated checks concurrently, and one merge lane applies
overlapping patches.

Parallelism should follow bottlenecks rather than a fixed worker count:

- one canonical CUDA trainer;
- zero or more snapshot evaluators, bounded by CPU and memory leases;
- Hammer concurrency bounded by actual nested solver children;
- one persistent Leanstral model service with continuous request batching;
- Codex workers bounded by ready disjoint scopes, validation capacity, and merge
  conflict rate;
- one serialized overlapping-write merge lane;
- asynchronous, atomic disagreement export and checkpoint persistence.

## Optimization Waves

### Wave A: Make Quality Signals Causal

Prove metric lineage and responsiveness, wire trainable learned LegalIR heads to
the evaluated objective, make representation promotion evidence mandatory, and
measure the causal effect of trusted Hammer/Leanstral feedback. Optimize each
view family independently under hard proof, provenance, structural, and
anti-copy constraints.

### Wave B: Improve Formal Supervision

Measure obligation coverage by family and contract field, minimize verified
counterexamples, trigger Leanstral only where it adds information, and preserve
complete state-to-receipt-to-TODO-to-patch-to-next-cycle attribution.

### Wave C: Remove Runtime Serialization

Profile and batch projection updates on CUDA, keep stable tensors resident,
activate asynchronous snapshot evaluation, coalesce immutable compiler and
embedding artifacts, move export/checkpoint writes off the cycle path, and fix
GPU/resource telemetry.

### Wave D: Adapt Parallelism

Allocate Hammer, evaluator, validation, and Codex workers from measured queue
pressure and resource leases. Use early-stopped, resource-aware hyperparameter
search rather than blindly running every candidate for the full budget. Batch
Leanstral requests continuously and scale Codex only when useful disjoint work
and downstream validation capacity exist.

### Wave E: Promotion

Benchmark cold and warm operation, run the integrated smoke, then a one-hour
search, eight-hour canary, and twenty-four-hour production run. Promotion fails
closed on incomplete snapshot lineage, invariant or non-responsive learned
metrics, absent representation reports, stale guidance, unverified proof signal,
source-copy reward hacking, orphaned children, or degraded accepted patches per
wall-clock hour.

## Success Criteria

- Controlled learned-head perturbations change learned IR metrics, while
  deterministic compiler mutations change deterministic compiler metrics.
- Learned IR CE/cosine and deterministic compiler IR CE/cosine use the same
  frozen examples but retain explicit, independently versioned lineage.
- Trusted guidance produces measurable, correctly directed updates; untrusted,
  stale, duplicate, and holdout-leaking records produce none.
- Every required LegalIR family has obligation and counterexample coverage.
- Projection-training p95 falls by at least 40 percent without a quality or
  trust regression, and CUDA trainer duty cycle exceeds 70 percent.
- Useful CPU utilization stays between 70 and 90 percent under load without
  swap growth, runaway child processes, or GPU-memory admission failures.
- Immutable compilation and embedding artifacts are computed once per matching
  digest and shared across baseline, guided, train, validation, and proof lanes.
- Autoencoder-cycle overhead attributable to Hammer/Leanstral remains below 10
  percent when asynchronous work is excluded from the critical path.
- Task-to-accepted-patch rate improves by at least 20 percent and state-to-merged
  patch latency falls by at least 25 percent against a matched baseline.
- No unverified Leanstral assertion or copied source span becomes a learned
  target, proof fact, or deterministic compiler rule.

The executable work derived from this plan is tracked as
`PORTAL-LIR-HAMMER-054` through `PORTAL-LIR-HAMMER-072` in
`docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md`.
