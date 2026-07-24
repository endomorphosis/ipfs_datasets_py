# HSSL-BENCH-034 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-034
Title: Close objective gap: Reconcile source and submodule freshness in a new run namespace
Goal: HSSL-G113 — Reconcile source and submodule freshness in a new run namespace
Priority: P0
Track: benchmark-remediation
Attempt: 1
Depends on: none
Missing evidence: HSSLEV1134D84
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-24-hssl-bench-034-objective-gap-7e8e81fcf9ad.md`
Source fingerprint: `7e8e81fcf9add2fb91bae7a520e1ce732351b3f8`
Source todo: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/objective_bundles/objective-hssl-remediation-source-isolation.todo.md`
Source line: 7
Todo vector index: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/objective_bundles/todo_vector_index.json`
Todo vector: `8126954460dd33e2`
Merge key: `599e29f75972f9fe`
Merge family: `objective/HSSL-G113`
Merge role: aggregate
Surplus group: `objective/HSSL-G113`
Candidate kind: aggregate
Work item count: 1
Work scope: `goal_subgoal_multi_evidence_batch`
Bundle: `objective/hssl/remediation-source-isolation`
Parallel lane: `objective/hssl/remediation-source-isolation`
Graph depth: 14
Parent goals: HSSL-G100
Expected outputs: `data/agent_supervisor/discovery`,
`docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`,
`benchmarks/logic_pipeline/source_reconciliation.py`,
`tests/integration/benchmarks/logic_pipeline/test_source_reconciliation.py`,
`workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/state/baseline-manifest.json`
Validation: `python -m pytest tests/integration/benchmarks/logic_pipeline/test_source_reconciliation.py tests/integration/benchmarks/logic_pipeline/test_worktree_isolation.py tests/integration/benchmarks/logic_pipeline/test_baseline_runner.py -q`
Acceptance: Establish a fresh detached benchmark source, exact recursive
submodule gitlinks, environment inventory, state root, and cache namespaces
without rewriting any frozen v1 manifest, result, or decision.

## Evidence

- `benchmarks.logic_pipeline.source_reconciliation.HSSLEV1134D84` is the
  stable AST evidence symbol. The separate
  `SourceReconciledBaselineManifest` contract, strict canonical loader,
  exclusive writer, recursive Git traversal, environment binder, namespace
  validator, normalized-output comparator, and reconciliation coordinator
  make the source-freshness boundary executable and tamper-evident.
- The historical baseline remains schema
  `ipfs-datasets.logic-pipeline-benchmark.frozen-baseline-manifest.v1`,
  semantic identity
  `6b37a6493d6328102b558258843218128ad0bf6f8cc7be13f8d0c2e0bb61e156`,
  raw file identity
  `063caddfa99fcb0307d59fdefb3a6313c194e1dc07054e92254b7d6dc2bca8fa`,
  and source commit `2a1be00b1b76e6652c25d418752affbf0f85d176`.
  It is an immutable predecessor input, not a manifest to refresh in place.
  The v1 validator now compares its gitlinks with that pinned commit tree,
  avoiding the prior error of treating an ambient newer index as historical
  drift while retaining exact source verification.
- The canonical v2 receipt is
  `workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/state/baseline-manifest.json`.
  Its reconciliation-owned schema is
  `ipfs-datasets.logic-pipeline-benchmark.source-reconciled-baseline.v1`
  and its semantic digest is
  `6c7084db784022d81abc65148fb0d72a8046da881c4d4b448434b9b13af7e469`.
  It binds fresh detached outer commit
  `3e053f6edece026fef48c153aa5c4d62a50da3d2` and twenty sorted
  recursive gitlinks: ten in the outer repository and ten beneath the pinned
  `ipfs_accelerate_py` tree. Traversal reads pinned commit trees and rejects
  a missing child repository/object instead of allowing Git to climb from an
  uninitialized submodule path and return a partial inventory.
- The only relevant outer gitlink advance is `ipfs_accelerate_py`, from
  `d3db5eea637a69c2e919b1c850f0f0089071cbcb` to
  `0c27224e02b91ebd102647f93781ca2b27e9cd88`; its nested gitlinks are
  unchanged and its source delta is supervisor maintenance. Both exact A0
  treatment route files are byte-identical to v1. Two real complete A0 pilot
  runs, covering cold and warm modes for all ten pilot cases, normalize to
  digest
  `599e85c5c19c87c370cdf28f8a156ff5af3fc6f6c186028c963c84f659319b22`.
  Normalization excludes run IDs, receipt-derived hashes, and volatile timing
  and memory only; it retains coordinate, status/failure, route/adapter,
  semantic data/output digest, effective identity, and provenance. Any
  unexplained semantic or trust-field drift fails closed.
- The fresh pre-repair environment snapshot is bound to the v2 run and source
  as digest
  `141e63efa862766f860673494bad3406b9b8f0fd40dd4c634822e21326734738`.
  It truthfully records CPython 3.12.3, spaCy 3.8.14, requested
  `en_core_web_sm`, the effective `spacy.blank:en` fallback, and HSSL-G120 as
  the later full capability re-probe. Secret-bearing keys are rejected rather
  than serialized.
- Run `reassessment-v2` owns disjoint state, results, receipts, detached
  worktree, process, cold-cache, and warm-cache namespaces below its own run
  root. Both run contracts bind the same frozen protocol, corpus, A0
  configuration, and pilot split while using distinct cold/warm namespaces.
  Validation rejects path overlap, cache collision, a v1 run reference, or a
  source/environment mismatch.
- The coordinator delegates detached preparation to the existing
  worktree-safety boundary, records its receipt, initializes recursive
  submodules only from locally provisioned exact objects (`--no-fetch`),
  snapshots every named v1 artifact before and after, verifies active checkout
  stability, and exclusively creates v2 evidence. It never cleans, resets,
  stashes, switches, merges, overwrites, changes production routing, or
  rewrites a v1 manifest, result, or decision.

## Validation

Required command:

```text
python -m pytest tests/integration/benchmarks/logic_pipeline/test_source_reconciliation.py tests/integration/benchmarks/logic_pipeline/test_worktree_isolation.py tests/integration/benchmarks/logic_pipeline/test_baseline_runner.py -q
```

Result: 39 passed. The required suite covers the AST evidence marker; checked
canonical manifest and exact v1 bytes; strict parsing, duplicate keys,
noncanonical JSON, redigested tampering, and exclusive writes; pinned nested
gitlink traversal versus active heads and uninitialized-submodule failure;
source/environment binding; treatment and twenty-coordinate normalized pilot
equivalence; deliberate semantic, status, cardinality, and order drift;
namespace separation/collision; detached active-checkout isolation; and
compatibility with the unchanged v1 baseline runner.

The complete logic-pipeline unit and integration suite also passes: 435
tests. Python bytecode compilation and repository whitespace validation pass.

## Backlog alignment

HSSL-G113 remains one cohesive bounded aggregate. Source and recursive gitlink
identity, environment binding, A0 behavior equivalence, namespace separation,
and predecessor immutability are one authorization boundary for the v2
baseline, so no child goal, parent edge, or output refinement is needed.

Generated todo-vector, objective-bundle, and task-status metadata remain
supervisor-owned and were not edited manually. The supervisor can reconcile
vector `8126954460dd33e2` and merge key `599e29f75972f9fe` from
HSSLEV1134D84, the canonical v2 manifest, objective heap, this discovery
receipt, and the required validator.
