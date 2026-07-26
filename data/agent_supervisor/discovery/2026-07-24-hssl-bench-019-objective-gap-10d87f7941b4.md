# HSSL-BENCH-019 Objective Gap Resolution

Date: 2026-07-24
Fingerprint: 10d87f7941b454ee89501148891d6d0307b60dc4
Task: HSSL-BENCH-019
Goal: HSSL-G050 — Implement the stage-aware ablation runner
Missing evidence: HSSLEV0501F2F
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-019-objective-gap-10d87f7941b4.md`
Source fingerprint: `10d87f7941b454ee89501148891d6d0307b60dc4`
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Todo vector: `15aef373784635ec`
Merge key: `5434d6aa68a35987`
Merge family: `objective/HSSL-G050`
Work scope: `goal_subgoal_multi_evidence_batch`

## Evidence

- `benchmarks.logic_pipeline.runner.HSSLEV0501F2F` is the stable AST
  evidence symbol for stage-aware, paired, resumable ablation execution.
- `benchmarks.logic_pipeline.variants.VARIANT_REGISTRY` contains exactly one
  immutable `VariantDefinition` for every frozen A0 through A12 arm and the S1
  safety diagnostic. Each definition names its canonical stage route, parser
  and routing modes, proof-order policy, capability requirements, safety-only
  status, and requested configuration identity. A6 represents Leanstral-first
  as an explicit proof-order policy while retaining canonical `StageName`
  record order as required by `CaseResultRecord`.
- `ResourceLimits`, `ScheduledCase`, `AblationPlan`, and
  `build_ablation_plan` create a content-addressed execution plan that binds
  protocol, corpus, split, registry, requested variants, cold/warm modes,
  resource limits, requested configuration identities, and the operator seed
  before execution begins. Every `(case, cache mode)` is one paired block whose
  arms receive the same self-contained immutable case payload and payload
  digest.
- Seed-bound SHA-256 ranks randomize and record block and within-block arm
  order deterministically. Rebuilding a plan with the same inputs reproduces
  its task order and identity; changing a frozen input changes or invalidates
  the plan.
- Every task receives a validated `RunContract` and `CacheScope` that isolate
  run, protocol, variant, split, and cache mode. Requested and effective arm
  IDs must match. Missing or degraded required capabilities produce a durable
  unavailable result for the requested arm and never trigger substitution.
- `execute_ablation` retains every terminal disposition, including capability
  exclusions, stage failures, infrastructure failures, and raised backend
  exceptions, as one canonical immutable per-job result file. Resume reparses
  the plan and every existing result, skips only an exact completed task
  identity, and rejects duplicate, corrupt, stale, foreign, or conflicting
  evidence rather than rerunning or hiding it.
- The frozen A0 validation and execution API and documented command-line
  behavior remain available alongside the broader ablation runner.

## Validation

Required command:

```text
python -m pytest tests/integration/benchmarks/logic_pipeline/test_runner.py -q
```

Focused integration coverage verifies complete registry/route definitions,
requested/effective identity, deterministic seed and order recording, identical
paired inputs, run/variant/split/cache isolation, explicit capability
unavailability, durable failure accounting, exact resume skipping, corrupt or
conflicting resume rejection, and preservation of the legacy A0 boundary.

Results:

- Required focused integration command: 11 passed.
- Complete unit and integration logic-pipeline benchmark suite: 260 passed.
- Frozen A0 validate-only command: passed and reported the pinned manifest,
  ten pilot cases, and distinct cold/warm modes.
- Python bytecode compilation and repository diff checks: passed. The optional
  `ruff` executable was not installed in this environment.

## Backlog alignment

HSSL-G050 is one cohesive bounded execution goal: the explicit variant registry
and the paired scheduler/persistence boundary change together and share one
focused integration suite. The implementation, objective-heap evidence, and
this supervisor discovery receipt cover HSSLEV0501F2F without a smaller child
goal. Existing HSSL-G051, HSSL-G052, and HSSL-G053 remain the correctly scoped
children for front-end overlap, proof ordering, and conditional delegation.
Generated todo-vector, objective bundle, and task status remain
supervisor-owned and were not edited manually.
