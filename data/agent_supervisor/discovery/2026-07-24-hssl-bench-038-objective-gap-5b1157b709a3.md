# HSSL-BENCH-038 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-038 — Close objective gap: Re-probe and freeze the repaired runtime capabilities
Goal: HSSL-G120
Missing evidence: HSSLEV1207F16
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-24-hssl-bench-038-objective-gap-5b1157b709a3.md`
Source fingerprint: `5b1157b709a352e29b5237fa0e9c3f968fefb823`
Source todo: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/objective_bundles/objective-hssl-capability-reprobe.todo.md` line 7
Todo vector: `e2062708a3e33ac4`
Merge key: `239c12133fc46c4c`
Merge family: `objective/HSSL-G120`
Merge role: aggregate
Candidate kind: aggregate
Work scope: `goal_subgoal_multi_evidence_batch`
Bundle and lane: `objective/hssl/capability-reprobe`
Parent goals: HSSL-G110, HSSL-G111, HSSL-G112, HSSL-G113, HSSL-G114

## Evidence

- `benchmarks.logic_pipeline.runtime.HSSLEV1207F16` and
  `benchmarks.logic_pipeline.capability_reprobe.HSSLEV1207F16` are the stable
  AST-verifiable code receipts.
- `capability_reprobe.run_live_capability_reprobe` revalidates the detached
  `reassessment-v2` source manifest, then uses only fixed non-corpus inputs to
  exercise the full spaCy pipeline, SyMAI and the existing `llm_router`,
  Hammer/cvc5, the shared Leanstral service, Lean/Lake, the run-scoped cache,
  and the resource scheduler. A separate native-kernel smoke compiles an
  identity theorem with the pinned Lean executable.
- The canonical inventory at
  `workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/receipts/capability-inventory.json`
  has semantic SHA-256
  `9a3d1c61f9d09ebedee0ff446fb9aa72808a467ff1ea41feb8ca204eacb9948b`.
  All eight registered capabilities are `available`, requested identity
  equals effective identity, and every row joins to a bounded live receipt.
- `capability-freeze.json`, semantic SHA-256
  `2446b48d1550fd5792ac9b126dd9fa2785d251f01c1ddc7afcae019889336252`,
  cross-validates every receipt byte and semantic digest, source commit,
  detached worktree receipt, recursive gitlinks, environment, cache
  namespace, native-kernel authority, and the no-corpus/no-holdout safety
  state. It rejects drift, fallback, unavailable/degraded status,
  noncanonical evidence, traversal/symlinks, and secret-bearing records.
- The public snapshot is
  `docs/performance_snapshots/2026-07-24_hssl_reassessment_capability_inventory.json`.
  It authorizes only the unchanged reassessment matrix; it does not access
  holdout inputs, promote a component, or change production routing.

## Validation

Commands:

```text
python -m benchmarks.logic_pipeline.runtime probe --require spacy_pipeline,symai,llm_router,hammer,leanstral_service,lean_toolchain
python -m benchmarks.logic_pipeline.runtime probe --require spacy_pipeline,symai,llm_router,hammer,leanstral_service,lean_toolchain --validate-freeze
python -m pytest tests/integration/benchmarks/logic_pipeline/test_capability_reprobe.py -q
```

The live required probe and strict frozen-evidence validation both exited
zero. The live inventory reported every required backend, cache, and scheduler
as available and emitted independent native-kernel receipt
`9c341ffbf7eefb6c517b43a028f5a5183813867ce471576b1f134527665ff92d`.

## Backlog alignment

HSSL-G120 remains one cohesive pre-matrix authorization goal. Detached-source
identity, live component smokes, independent kernel authority, secret and
fallback rejection, and the aggregate freeze are one indivisible eligibility
decision, so no smaller child goal is needed. The generated todo vector,
objective bundle, external benchmark todo, and task status remain
supervisor-owned and were not manually edited. The supervisor can reconcile
HSSLEV1207F16 from the AST symbols, canonical inventory/freeze/snapshot,
objective heap, this discovery receipt, and the required validator.
