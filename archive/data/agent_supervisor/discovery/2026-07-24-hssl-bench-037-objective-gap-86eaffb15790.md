# HSSL-BENCH-037 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-037
Title: Close objective gap: Implement fail-closed authorized holdout and detached replay orchestration
Goal: HSSL-G116
Priority: P0
Track: benchmark-remediation
Attempt: 1
Depends on: none
Missing evidence: HSSLEV1167A17
Source finding: /home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-24-hssl-bench-037-objective-gap-86eaffb15790.md
Source fingerprint: 86eaffb1579088275a735211749edf8c51c0480f
Source todo: /home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/objective_bundles/objective-hssl-remediation-holdout-replay.todo.md
Source line: 7
Objective heap: docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md
Todo index: /home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/objective_bundles/todo_vector_index.json
Todo vector: 708afce4d891c556
Merge key: 77d3c3dfb87d1e0d
Merge family: objective/HSSL-G116
Surplus group: objective/HSSL-G116
Merge role: aggregate
Candidate kind: aggregate
Work item count: 1
Work scope: goal_subgoal_multi_evidence_batch
Bundle: objective/hssl/remediation-holdout-replay
Graph parent: HSSL-G100
Graph depth: 14
Expected outputs: data/agent_supervisor/discovery, docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md, benchmarks/logic_pipeline/holdout_execution.py, benchmarks/logic_pipeline/replay.py, tests/integration/benchmarks/logic_pipeline/test_authorized_holdout_execution.py, tests/integration/benchmarks/logic_pipeline/test_fresh_worktree_replay.py
Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_authorized_holdout_execution.py tests/integration/benchmarks/logic_pipeline/test_fresh_worktree_replay.py -q

## Evidence

`benchmarks.logic_pipeline.holdout_execution.HSSLEV1167A17` is the stable AST
evidence symbol for HSSL-G116.

`PilotAuthorizationReceipt` is a strict, frozen, content-addressed handoff from
a passed pilot gate. It requires a nonempty shortlist of at most four distinct
registered nonbaseline arms and binds the exact pilot-gate digest, source
commit, environment, frozen protocol, reviewed corpus and holdout split,
prompts, policy, model identities, thresholds, and configuration digest for A0
and every shortlisted arm. An incomplete, empty, unauthorized, already
inspected, tuning-enabled, tampered, or drifted handoff cannot be constructed
or deserialized.

`build_authorized_holdout_plan` schedules exactly A0 plus the frozen shortlist
over every case in the immutable holdout manifest, retaining manifest order,
identical paired inputs, separate cold and warm modes, and seeded
counterbalanced arm positions. The shared ablation contract now derives a
unique deterministic audit ID for each holdout variant/cache contract from the
plan's access-ledger identity. `build_holdout_access_audits` and
`execute_authorized_holdout` require one contiguous, unique
`HoldoutAccessAudit` per contract, with evaluation purpose and exact
run/variant/cache/corpus/split/configuration/prompt/policy/model/threshold
identities. Tuning remains false. All authorization, manifest, schedule,
source, environment, audit, adapter-map, resource-scheduler, and fresh-output
checks finish before any output path is created or any backend is invoked.
Generic `execute_ablation` still rejects holdout, and authorized holdout resume
or overwrite is impossible.

`ReplayRequest`, `ReplayReceipt`, and `run_detached_replay` authenticate the
source holdout receipt and source worktree receipt before allocating replay
state. Replay requires a new run ID, live source worktree at the receipt-bound
commit, identical environment, a distinct process namespace, a distinct cold
cache namespace, and a nonexistent run root. It uses
`prepare_isolated_worktree` at the exact commit and recursive gitlinks, verifies
the new worktree's live detached HEAD, executes a bounded command without a
shell in a new process session, and accepts only a bounded regular non-symlink
evidence file below the replay run root. Its canonical replay receipt is
create-only and binds the source and replay worktree receipts, source
execution, request, source/environment, process/cache namespaces, command
outputs, and evidence bytes. `validate_detached_replay_pair` composes the
orchestration proof with the established strict result/backend/kernel
reconstruction replay validator.

The integration coverage uses backend-call counters to prove unauthorized,
drifted, incomplete-audit, wrong-purpose, direct-generic, and occupied-output
attempts perform zero calls and zero writes. A real disposable Git repository
proves exact detached replay, active dirty-checkout preservation, isolated
state/process/cache namespaces, environment-drift rejection before state
creation, stale live-worktree rejection, and replay-run nonreuse.

This is structural orchestration evidence only. It did not open or execute the
real holdout and makes no efficacy, safety, cost, or replay-success claim for
the benchmark. HSSL-G150 retains the real authorized holdout execution and
HSSL-G160 retains the real detached replay and publication.

## Validation

The required validator passed:

`python -m pytest tests/integration/benchmarks/logic_pipeline/test_authorized_holdout_execution.py tests/integration/benchmarks/logic_pipeline/test_fresh_worktree_replay.py -q`

Result: 12 passed.

The focused suite covers canonical record round trips and tamper rejection,
the complete holdout case/cache/arm product, counterbalanced identical-input
blocks, one unique no-tuning audit per contract, write-once records, zero
side-effects on failed authorization, real detached Git worktrees, source
commit/environment freshness, isolated process/cache/run namespaces, active
checkout preservation, stale receipt rejection, and run namespace nonreuse.

## Backlog alignment

HSSL-G116 remains one cohesive trust-boundary goal: authorization and detached
replay jointly control the only permitted transition from frozen pilot
selection to holdout evidence. No smaller child goal, new parent edge, or
output refinement is needed. HSSL-G150 and HSSL-G160 already separate the later
real execution and publication work.

The objective heap now records the implementation and validation contract.
The external objective bundle, todo-vector index, generated task state, and
status remain supervisor-owned and were not edited manually. Their existing
goal ID, missing-evidence ID, bundle, merge family/key, output set, and
validation command already agree with this receipt, so reconciliation remains
validation-driven.
