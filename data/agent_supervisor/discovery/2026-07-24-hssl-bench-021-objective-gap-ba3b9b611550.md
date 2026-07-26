# HSSL-BENCH-021 Objective Gap Resolution

Date: 2026-07-24
Fingerprint: ba3b9b61155034a561ba68b6e8514a87b99c7d76
Task: HSSL-BENCH-021
Goal: HSSL-G053 — Implement and compare conditional delegation policies
Missing evidence: HSSLEV0533D02
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-021-objective-gap-ba3b9b611550.md`
Source fingerprint: `ba3b9b61155034a561ba68b6e8514a87b99c7d76`
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Todo vector: `d4be29753d948ded`
Merge key: `9aa5482048029b6f`
Merge family: `objective/HSSL-G053`
Work scope: `goal_subgoal_multi_evidence_batch`

## Evidence

- `benchmarks.logic_pipeline.delegation.HSSLEV0533D02` is the stable AST
  evidence symbol for bounded P0-P3 routing and paired policy comparison.
- `DelegationPolicyConfig`, `DelegationThresholds`, and
  `LearnedRouterProvenance` are immutable, canonically serialized, and
  content-addressed. All four policies carry the exact same frozen protocol,
  complete `ResourceLimits` payload and digest, three-component allowlist,
  one-fallback ceiling, and native-kernel verification authority.
- P0 invokes spaCy, SyMAI, Hammer, and Leanstral exactly once as the
  upper-cost arm. P1 gates SyMAI on ambiguity, missing predicates, schema
  rejection, or confidence below the frozen threshold; sends valid
  obligations to Hammer; and adds Leanstral only for an inconclusive, failed,
  or reconstruction-failed Hammer attempt. P2 selects Hammer first for
  FOL/SMT/unknown proof families and Leanstral first for Lean-native,
  dependent-type, or tactic-heavy families, then may cross the boundary once.
- P3 accepts only scores from a pinned selector trained on development
  telemetry. Every decision retains the selector, feature-schema, training
  manifest, algorithm, seed, per-case feature-vector, score, and threshold
  identities. Threshold comparisons are explicit and inclusive. Holdout
  routing fails closed unless thresholds were frozen before access; training
  provenance containing pilot or holdout membership is rejected.
- `RoutingSignals` contains routing-safe evidence and has no expected answer,
  expected IR, or ground-truth field. `route_case` is pure and imports or calls
  no optional backend. A decision stores canonical durable stage order
  separately from proof invocation order, invokes the native kernel last,
  rejects component re-entry, enforces model/solver ceilings, and never
  treats a route or learned score as proof authority.
- `DelegationObservation` requires a native-kernel receipt for a verified
  outcome and permits useful-component attribution only for invoked components
  supporting that verified gain. Non-verified and already deterministically
  resolved cases cannot manufacture useful delegation evidence.
- `compare_delegation_policies` accepts only a complete, unique, paired P0-P3
  matrix over pilot/development cases with identical case, split, cache,
  input, protocol, manifest, paired-label, and resource identities. It retains
  every observation digest and separately reports verified rate, component,
  model, and solver calls, escalation precision and recall, early resolution,
  and Pareto membership.
- Unnecessary-call rate has an executable denominator:
  `(component calls - kernel-verified useful component calls) / component
  calls`, with an explicit result of zero when no component is called.

## Validation

Required command:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline/test_delegation.py -q
```

Results:

- Required focused unit command: 35 passed.
- Complete logic-pipeline benchmark unit suite: 198 passed.
- Python bytecode compilation for the delegation module: passed.
- Repository diff check: passed.

The focused suite covers exact P0-P3 routes, every deterministic SyMAI trigger,
confidence and learned threshold boundaries, both proof-family directions,
single fallback and no-bounce behavior, development-only learned provenance,
holdout freeze enforcement, decision/configuration round trips and tamper
rejection, dependency-free import, identical resource and verification
boundaries, kernel-bound usefulness, complete paired inputs, exact
unnecessary-call accounting, zero denominators, and mixed/duplicate/missing
evidence rejection.

## Backlog alignment

HSSL-G053 is already a cohesive bounded analysis child of HSSL-G050: policy
configuration, routing, provenance, resource enforcement, and paired efficiency
accounting form one dependency-free contract and focused suite. No smaller
child goal is needed. The implementation, objective-heap evidence, and this
supervisor discovery receipt cover HSSLEV0533D02. Generated todo-vector,
objective-bundle, and task-status metadata remain supervisor-owned and were not
edited manually.
