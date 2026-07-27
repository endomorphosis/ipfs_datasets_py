# HSSL-BENCH-029 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-029
Goal: HSSL-G051 — Measure spaCy and SyMAI front-end overlap
Missing evidence: HSSLEV0519C80
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-029-objective-gap-c06ca371072f.md`
Source fingerprint: `c06ca371072f0c5cde22e44c1ac46ac15a418f3f`
Todo vector: `b62a909be7ab54e0`
Merge key: `ec0cd62cb07c690b`
Merge family: `objective/HSSL-G051`
Work scope: `goal_subgoal_multi_evidence_batch`

## Evidence

- `benchmarks.logic_pipeline.report.HSSLEV0519C80` is the stable AST evidence
  symbol for the spaCy/SyMAI front-end overlap report boundary.
- The canonical result
  `workspace/benchmarks/hammer-symai-spacy-leanstral/results/frontend-overlap-v1.json`
  is content-addressed as
  `86cc7263efe890a80e0ecf3518eaefaad8dfbabb4fb35d544be83905e4c32404`.
  It binds the frozen protocol and variant registry, reviewed corpus and split
  identities, exact case-to-stratum mapping, capability inventory, arm scope,
  cache modes, case observations, development selection, and recomputed
  analysis.
- Coverage is the complete 240-cell product of ten pilot and ten development
  cases, A0/A1/A4/A5/A7/A8, and cold/warm caches. The development cases are
  the complete reviewed split, selected without inspecting outcomes because
  no smaller case shortlist was preregistered. Holdout cases remain outside
  the report.
- Every measured aggregate is derived from case-level evidence and separated
  by split, cache, and stratum: normalized-IR exact match, deterministic
  semantic equivalence, ambiguity classification, unsupported/fail-closed
  classification, p50/p95 latency, model calls, semantic disagreements,
  component-unique wins, regressions against A0, and unnecessary SyMAI calls.
  Disagreement records retain both semantic signatures and both correctness
  outcomes rather than collapsing them into a count.
- Measured rows fail closed unless they embed a strict `CaseResultRecord` whose
  case, split, cache, requested arm, route prefix, semantic payload digest,
  stage presence, latency, and model-call telemetry match the observation.
  Requested full spaCy, regex/legal, blank-model, gated-SyMAI, and always-on
  SyMAI policies are checked against the frozen registry; one arm can never
  silently become another.
- The requested matrix supports descriptive spaCy/SyMAI overlap. A4/A1,
  A7/A1, and A8/A1 are not labeled causal SyMAI marginal effects because they
  also differ in other stages; only A5/A4 is labeled as the gate-efficiency
  control.
- Runtime preflight found the current codec, regex/legal parser, and blank
  model available, the requested full spaCy model unavailable, and
  SyMAI/router provider-model identities degraded. All 240 cells are retained
  as capability-unavailable with null semantic metrics. This is durable
  missingness evidence, not a semantic loss, zero-cost result, or silent
  fallback. The dated performance snapshot records the same limitation and
  exact replay prerequisites.

## Validation

Required command:

```text
python benchmarks/logic_pipeline/report.py --section frontend --validate
```

The command validates canonical strict JSON, immutable protocol/corpus/arm
identities, exact case/stratum joins, complete paired scope, canonical
observation order, capability missingness, recomputed analysis, content
digest, and measured-replay source binding.

Results:

- Required front-end validation command: passed; 240 observations retained
  across two splits, ten strata, six arms, and two cache modes, with zero
  fabricated semantic measurements and explicit missingness.
- Focused front-end and proof report suites: 19 passed.
- Complete logic-pipeline unit and integration suite: 279 passed.
- Existing proof-report validation remains compatible and passed.
- Python bytecode compilation and repository whitespace checks: passed.

## Backlog alignment

HSSL-G051 remains one cohesive front-end reporting goal. Its validator owns
initial preflight evidence and future measured replay validation, so the
capability gap does not justify a smaller code child or substitute arm. The
objective heap now names the evidence symbol, canonical artifact, metrics,
missingness, and selection boundary. Generated todo-vector, objective-bundle,
and task status remain supervisor-owned and were not edited manually; the
supervisor can reconcile HSSLEV0519C80 from the AST symbol, immutable artifact,
and required validation receipt.
