# HSSL-BENCH-020 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-020
Goal: HSSL-G052 — Measure Hammer and Leanstral proof overlap and ordering
Missing evidence: HSSLEV0526A41
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-020-objective-gap-9872b86dbe18.md`
Source fingerprint: `9872b86dbe1866f0cbec88182cf92f21b78d0620`
Todo vector: `a93b3e6b04f823c0`
Merge key: `c983d5e4e8922143`
Merge family: `objective/HSSL-G052`

## Evidence

- `benchmarks.logic_pipeline.report.HSSLEV0526A41` is the stable AST evidence
  symbol for the Hammer/Leanstral overlap and ordering report boundary.
- The canonical result
  `workspace/benchmarks/hammer-symai-spacy-leanstral/results/proof-overlap-ordering-v1.json`
  is content-addressed as
  `dae3faa6af66d5a78156dad69fb93151c8f600a1d7f07bada8e7ae6943eef9b9`.
  It binds the frozen protocol, variant registry, reviewed corpus, pilot split,
  runtime capability inventory, eligible and excluded case identities, arm
  scope, cache modes, observations, and recomputed analysis.
- Coverage is the complete 154-cell product of seven eligible pilot proof
  obligations, A2-A4 and A6-A12 plus S1, and cold/warm cache modes. Missing,
  duplicate, reordered, or foreign cells fail validation. A6 and A12 retain
  their Leanstral-first policy despite canonical stage-record serialization;
  A9 remains no-Hammer; A10 and A11 remain learned-selector and LLM-ranker
  controls.
- Every primary metric is derived from case observations: premise recall,
  Hammer and Leanstral candidate creation and overlap, reconstruction attempts
  and successes, bounded repair attempts and successes, end-to-end latency,
  model calls, component-unique verified wins, and the preregistered ordering,
  no-Hammer, selector, ranking, and duplicated-work comparisons.
- Verification fails closed. A `verified` row requires native-kernel authority,
  explicit acceptance, and a kernel-receipt digest. Hammer reconstruction and
  model claims have no authority by themselves. S1 cannot serialize a verified
  result or enter any primary aggregate.
- The frozen corpus lacks independently reviewed Hammer premise-ID sets.
  Premise recall is therefore retained as unmeasured with
  `gold_premise_set_unavailable`; required predicates are not substituted for
  a premise denominator.
- Runtime preflight found Hammer/cvc5 and the native Lean kernel available, the
  requested spaCy pipeline and Leanstral service unavailable, and SyMAI/router
  identities degraded. The checked-in execution truthfully retains all 154
  observations as capability-unavailable and makes no efficacy claim. This is
  durable missingness evidence, not a scored failure or a silent variant
  substitution.
- The dated performance snapshot records the same artifact identity,
  capability state, null metrics, safety boundary, and exact prerequisites for
  a later measured replay.

## Validation

Required command:

```text
python benchmarks/logic_pipeline/report.py --section proof --validate
```

The command validates canonical strict JSON, immutable identities, complete
paired scope, policy ordering, observation invariants, kernel authority,
aggregate recomputation, artifact digest, missingness, and S1 isolation. The
focused unit suite additionally exercises positive measured aggregation,
Hammer-unique wins, nullable premise recall, forged verification, S1 claims,
matrix omissions and duplicates, analysis/digest tampering, noncanonical JSON,
and the exact CLI.

Results:

- Required proof validation command: passed; 154 observations retained,
  execution mode `capability_preflight`, zero claimed kernel verifications, and
  missingness retained.
- Focused proof report suite: 8 passed.
- Complete logic-pipeline unit and integration suite: 268 passed.
- Python bytecode compilation and repository whitespace checks: passed.

## Backlog alignment

HSSL-G052 remains one cohesive proof-ablation reporting goal. Its validator
already covers initial execution, replay, comparison, trust enforcement, and
missingness, so capability unavailability does not require a smaller code
child goal or a substitute arm. The objective heap now names the evidence,
canonical artifact, measured terms, and capture limitation. Generated
todo-vector, objective-bundle, and task status remain supervisor-owned and were
not edited manually; the supervisor can reconcile HSSLEV0526A41 from the AST
symbol, immutable artifact, and required validation receipt.
