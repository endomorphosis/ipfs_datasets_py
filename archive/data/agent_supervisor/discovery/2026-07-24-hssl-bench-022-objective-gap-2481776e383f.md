# HSSL-BENCH-022 Objective Gap Resolution

Date: 2026-07-24
Fingerprint: 2481776e383f56581e60fa88d56e3ad56510d8a7
Task: HSSL-BENCH-022
Goal: HSSL-G070 — Validate robustness, replay, and failure isolation
Missing evidence: HSSLEV0702E85
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-022-objective-gap-2481776e383f.md`
Source fingerprint: `2481776e383f56581e60fa88d56e3ad56510d8a7`
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Todo vector: `71093dfa122e191d`
Merge key: `6c64adf41bad7ae2`
Merge family: `objective/HSSL-G070`
Work scope: `goal_subgoal_multi_evidence_batch`

## Evidence

- `benchmarks.logic_pipeline.report.HSSLEV0702E85` is the stable AST evidence
  symbol for failure injection, bounded isolation, and pinned fresh-worktree
  receipt replay.
- `FailureInjectionKind`, `FailureIsolationRecord`, and `RobustnessReport`
  require exactly one immutable, content-addressed observation for every
  preregistered incident: missing tool, malformed output, timeout,
  cancellation, cache corruption, and backend drift. Each observation must
  use the frozen failure taxonomy, remain within its recorded ceiling, affect
  exactly its injected case, and account for all started and reaped children.
- A failed or unavailable stage now short-circuits downstream work for that
  case. The scheduler continues with independent cases, so a backend exception
  is durable and local rather than cancelling or contaminating its neighbors.
- `run_bounded_process` launches commands without a shell in a new process
  group, keeps untrusted output off supervisor memory, applies timeout and
  explicit cancellation, sends TERM then KILL to the whole group, reaps the
  direct process, and verifies that no live descendant remains. Any survivor
  is classified as the immediate-stop `orphaned_child` outcome.
- `validate_replay` strictly reparses source and replay case receipts and their
  run contracts, validates all statuses against the pinned environment, and
  requires a new run ID, a new cold cache namespace, the same frozen
  configuration, and a detached worktree receipt at the expected commit.
  Stable route, adapter, requested/effective backend, input, output, terminal,
  kernel, and reconstruction identities must match.
- Corrupt stage or embedded receipt data, stale environment or source commit,
  same-cache reuse, a foreign run contract, and coherent backend drift all
  fail closed before replay evidence can enter a canonical robustness report.

## Validation

Required focused command:

```text
python -m pytest tests/integration/benchmarks/logic_pipeline/test_failure_isolation.py -q
```

Result: 7 passed. Coverage includes the complete injected-failure matrix,
per-case short-circuit and neighbor isolation, real timeout and explicit
cancellation of a parent/grandchild process group, zero surviving children,
fresh-run/cold-cache/worktree replay, strict corruption/staleness/backend-drift
rejection, and canonical report round-trip and immutability.

The complete benchmark logic-pipeline unit and integration suite also passed:
267 passed. Python bytecode compilation and repository diff checks passed. The
optional `ruff` module was not installed in this environment.

## Backlog alignment

HSSL-G070 remains a cohesive robustness aggregate and does not need another
child goal. HSSL-G071 and HSSL-G072 remain the correctly scoped children for
cache/backend-drift measurement and shared resource/process policy. Generated
todo-vector state, the objective bundle, and task status remain
supervisor-owned and were not edited manually; this receipt, the objective-heap
contract, executable AST evidence, and focused validation allow the supervisor
to reconcile HSSLEV0702E85.
