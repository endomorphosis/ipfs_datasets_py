# HSSL-BENCH-025 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-025
Title: Close objective gap: Execute the untouched paired holdout evaluation
Goal: HSSL-G090 — Execute the untouched paired holdout evaluation
Priority: P0
Track: benchmark-gate
Attempt: 1
Depends on: none
Missing evidence: HSSLEV0909F29
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-025-objective-gap-4bd3def209e3.md`
Source fingerprint: `4bd3def209e3a349b4dcf846981e22f62a461712`
Source todo: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/objective_bundles/objective-hssl-holdout.todo.md`
Source line: 7
Todo vector index: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/objective_bundles/todo_vector_index.json`
Todo vector: `7b35b522f57ce94a`
Merge key: `95185115ed14609d`
Merge family: `objective/HSSL-G090`
Merge role: `aggregate`
Surplus group: `objective/HSSL-G090`
Candidate kind: `aggregate`
Work item count: 1
Work scope: `goal_subgoal_multi_evidence_batch`
Bundle: `objective/hssl/holdout`
Graph depth: 12
Parent goal: HSSL-G080
Cluster: `todo/benchmark-protocol/385e65bc`
Expected outputs: `data/agent_supervisor/discovery`,
`docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`,
`workspace/benchmarks/hammer-symai-spacy-leanstral/results`,
`docs/performance_snapshots`
Validation: `python benchmarks/logic_pipeline/report.py --gate holdout`

## Evidence

- `benchmarks.logic_pipeline.holdout_gate.HSSLEV0909F29` is the stable AST
  evidence symbol for the strict paired holdout boundary, and
  `benchmarks.logic_pipeline.report.HSSLEV0909F29` exposes it through the
  required CLI.
- The canonical decision record is
  `workspace/benchmarks/hammer-symai-spacy-leanstral/results/holdout-evaluation-v1.json`;
  its semantic SHA-256 is
  `7d064c5fe82c25ad93c01fd13d4350ae2457f93d3bd32b9cf9a9365b1836c2cd`.
  `docs/performance_snapshots/2026-07-24_holdout_evaluation.json` publishes the
  point-in-time machine-readable result.
- The holdout gate strictly reloads the allowlisted canonical HSSL-G080 result
  and recomputes the entire report. HSSL-G080 is structurally valid but
  `incomplete`, with an empty frozen shortlist and an explicitly unauthorized,
  unopened holdout. It cannot support either A0-only access or a paired
  efficacy comparison.
- The HSSL-G090 decision is consequently `blocked` and `sealed_unopened`.
  No access audit, cache namespace, case result, measurement, kernel receipt,
  replay receipt, tuning event, efficacy claim, or production authority was
  created. Holdout manifest identities are bound, while semantic targets and
  outcomes remain uninspected.
- The seal binds protocol revision 1, the reviewed corpus, all ten ordered
  holdout case/source identities, the exact empty shortlist, A0, separate cold
  and warm modes, identical-manifest pairing, counterbalanced ordering, frozen
  budgets and thresholds, native-kernel-only success authority, and fresh
  worktree replay. These constraints cannot be weakened by editing the
  artifact because source-backed recomputation rejects redigested invention.
- All twelve candidate variants remain explicitly ineligible before holdout.
  Every safety, quality, latency, resource, and routing field is present,
  `not_observed`, null, and reason-bearing. True zero counts describe only the
  absence of authorized scheduling, access, observations, receipts, and
  replays; they are not presented as efficacy, zero cost, safety, or complete
  measured metrics.
- The generic ablation executor now rejects a holdout plan before creating
  files, allocating resources, or calling a backend. A caller-supplied
  `holdout_access_log_id` can no longer bypass the completed-pilot and
  per-contract access-audit requirement.

## Validation

Required command:

```text
python benchmarks/logic_pipeline/report.py --gate holdout
```

The command must return a source-revalidated summary with a `blocked` decision,
an untouched and unauthorized holdout, no selected variants or accesses, zero
scheduled and observed pairs, incomplete null metrics, no efficacy claim, and
no production promotion. It must reject stale source bindings, unknown fields,
noncanonical JSON, access/result/metric/replay invention, tuning, or any claim
that the prerequisite was satisfied.

Focused validation also covers the exact frozen manifest and budget bindings,
explicit candidate ineligibility, all five metric domains, replay missingness,
atomic writer behavior, CLI dispatch, and the generic-runner holdout bypass.

Validation results:

- Required holdout gate: passed. The canonical summary reports `blocked`,
  `structurally_valid=true`, `holdout_untouched=true`, authorization false,
  zero scheduled/observed pairs, incomplete null metrics, no efficacy claim,
  and no production promotion.
- Focused holdout-gate suite: 25 passed.
- Complete logic-pipeline unit suite: 295 passed.
- Cache-isolation, failure-isolation, and resource-bound integration suites:
  19 passed.
- Complete logic-pipeline integration suite: 109 passed and seven historical
  baseline-runner tests failed before exercising this change because the
  frozen A0 validator detects ambient submodule-gitlink drift in this objective
  worktree. The same environment-bound condition is documented by the
  preceding HSSL-G080 gate; the holdout implementation does not relax it.
- Python bytecode compilation, snapshot/artifact binding checks, and
  repository whitespace validation: passed. Ruff was not installed in the
  execution environment, so no Ruff result is claimed.

## Backlog alignment

HSSL-G090 remains a single cohesive phase-gate aggregate. Authorization,
untouched-state proof, paired scope and order, budgets, kernel authority,
replay, metrics, and sealing cannot be split without weakening the trust
boundary, so no child goal is needed.

The objective heap now names HSSLEV0909F29, the canonical result and snapshot,
the blocked prerequisite, untouched-holdout finding, full future execution
contract, null metrics, and runner bypass closure. Generated todo-vector,
objective-bundle, and task-status metadata remain supervisor-owned and were
not edited manually. The supervisor can reconcile the backlog from the AST
symbol, canonical artifacts, objective heap, this discovery receipt, and the
required validator.
