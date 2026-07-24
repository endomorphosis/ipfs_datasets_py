# HSSL-BENCH-023 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-023
Goal: HSSL-G060 — Produce reproducible statistics and Pareto analysis
Missing evidence: HSSLEV0608F63
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-023-objective-gap-215d1d9f5ecc.md`
Source fingerprint: `215d1d9f5eccaeb9446e26a0511b49fa38bff7f2`
Todo vector: `fcdf6c0dfffa5328`
Merge key: `fd4809b0c627e5d7`
Merge family: `objective/HSSL-G060`
Work scope: `goal_subgoal_multi_evidence_batch`

## Evidence

- `benchmarks.logic_pipeline.statistics.HSSLEV0608F63` is the stable AST
  evidence symbol for reproducible paired inference, explicit missingness,
  case-receipt traceability, multiplicity labeling, and direction-aware Pareto
  analysis. `benchmarks.logic_pipeline.report.HSSLEV0608F63` returns the same
  marker from the report entry point.
- `StatisticalPlan` freezes and content-addresses the seed, bootstrap sample
  count, confidence level, paired-stratified percentile method, R-7 quantile
  convention, exact two-sided McNemar/binomial method, and Holm exploratory
  adjustment. A comparison-specific seed is derived from the plan,
  comparison, and stratum scope so input/request ordering cannot perturb an
  existing interval and the process-global random state is untouched.
- `ComparisonSpec` admits only metrics and A0-paired non-diagnostic arms from
  the frozen protocol. It retains metric kind, estimator, direction, unit,
  preregistered or exploratory role, multiplicity family, and an explicit
  quality, safety, latency, resource, routing, or reliability domain instead
  of collapsing those decision dimensions into one score. The specification
  also identifies logic-family, difficulty, ambiguity, proof-route, or joint
  stratification, allowing the same receipt-bound pairs to be analyzed along
  each preregistered case partition without silently pooling it.
- `PairedCaseObservation` binds both source-result digests with run, case,
  corpus manifest, split, cache mode, variants, and stratum. `OutcomeRecord`
  and `CaseResultRecord` constructors reuse the existing paired trust boundary,
  including the native-kernel authority and fatal invalid-control checks.
  Logical failures and regressions stay in the numeric denominator. Only
  preregistered capability/fixture exclusions and infrastructure failures
  become explicit null observations with typed reasons.
- Seeded bootstrap resamples complete pairs within each stratum and reports
  overall plus per-stratum intervals. Continuous analysis supports paired
  means and paired medians and retains arm p50/p95/p99 distributions. Binary
  analysis reports baseline/candidate rates, absolute fraction and percentage
  point deltas, relative deltas with a zero-baseline reason, all four paired
  outcome cells and their case IDs, discordance status, and the exact
  two-sided p-value. Missing-only groups remain null rather than zero.
- Named exploratory families are deterministically Holm adjusted; primary
  analyses are explicitly labeled preregistered and unadjusted. Every
  aggregate includes canonical case traces with stratum, values, inclusion or
  missingness, both result receipts, and its observation digest.
- The generic Pareto frontier honors maximize/minimize directions and requires
  one strict improvement, so exact ties and genuine quality/cost trade-offs
  remain on the frontier. Report-only dimensions cannot dominate. Missing
  objectives are ineligible, and a safety violation is a hard infeasibility
  reason rather than a compensable score. Every candidate links to known
  analysis digests and exactly their underlying case-result receipts.
- The additive statistics report builder and validator preserve the existing
  front-end and proof schemas. Validation reloads strict canonical newline
  JSON, rejects duplicate keys, and recomputes all case aggregates, seeded
  intervals, binary tests, Holm adjustments, source links, Pareto decisions,
  and the artifact digest. The CLI accepts run-scoped evidence with
  `--section statistics --validate --results-path`.

## Validation

Required command:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline/test_statistics.py -q
```

The focused suite covers deterministic and input-order-independent bootstrap,
paired rather than independent resampling, strata, paired medians, exact
binary tables and p-values, percentage-point and relative effects, no
discordance, zero baselines, typed missingness and missing-only groups,
outcome eligibility, invalid values and identity mixing, exploratory Holm
families, Pareto direction/tie/missingness/safety behavior, aggregate and
frontier tamper rejection, strict canonical loading, additive CLI dispatch,
and canonical report construction.

Results:

- Required focused statistics suite: 25 passed.
- Existing front-end and proof report suites: 19 passed.
- Complete logic-pipeline unit suite: 242 passed.
- Complete logic-pipeline integration suite: 97 passed.
- Python bytecode compilation and repository whitespace checks: passed.

## Backlog alignment

HSSL-G060 remains one cohesive inferential-analysis work item: the statistical
plan, paired source boundary, missingness, confidence intervals, exact binary
analysis, multiplicity, traceability, Pareto decisions, and report validation
all operate on the same canonical evidence graph. No smaller child goal is
needed. HSSL-G061 remains the already-bounded child for marginal delegation
value and operational-complexity accounting. Generated todo-vector,
objective-bundle, and task-status metadata remain supervisor-owned and were not
edited manually.
