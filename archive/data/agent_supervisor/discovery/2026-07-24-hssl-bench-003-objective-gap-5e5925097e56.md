# HSSL-BENCH-003 Objective Gap Closure

Date: 2026-07-24
Task: HSSL-BENCH-003
Title: Close objective gap packet: HSSL-G072, HSSL-G071
Source finding: 2026-07-23-hssl-bench-003-objective-gap-5e5925097e56.md
Source fingerprint: 5e5925097e564c2bc4d5bceb3a026df89f37f3d7
Objective heap: docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md
Todo vector key: 2a2df72cf260f1de
Merge key: bd465da884b0d124
Merge family: goal_packet/benchmark_robustness/benchmarks/ac3639a861dc
Work scope: goal_subgoal_packet_aggregate; vector_ast_bundle
Primary goal: HSSL-G072
Packet goals: HSSL-G072, HSSL-G071
Packet siblings covered: HSSL-BENCH-007, HSSL-BENCH-009
Missing evidence closed: HSSLEV0724C07, HSSLEV0717A46

## Evidence

- `benchmarks.logic_pipeline.capabilities.HSSLEV0724C07` provides the stable AST evidence method for HSSL-G072. The implementation adds strict immutable resource policies, typed lane requests and duration-only receipts, a thread-safe bounded scheduler, identity-aware sharing of the single pinned 119B model service, distinct CPU/model/solver/kernel/validation capacities, bounded queue waits, measured queue delay, cooperative cancellation, and double-release/foreign-policy rejection.
- `benchmarks.logic_pipeline.capabilities.run_bounded_process_group` starts external solver or validation commands without a shell in a new process group, applies timeout plus TERM/KILL grace, bounds captured output, and waits for the process group to be reaped. Adversarial integration coverage creates a real solver child and proves that timeout leaves no live non-zombie child.
- The ablation executor acquires the correct resource class before each compiler, spaCy, SyMAI, Hammer, Leanstral, and kernel dispatch. A supplied scheduler cannot exceed the plan's frozen worker, memory, or solver ceilings. Queue timeout and cancellation remain local explicit `resource_lease_cancellation` results, while adapter telemetry continues to enforce case wall-time, memory, model-call, and solver ceilings after execution.
- `benchmarks.logic_pipeline.runner.HSSLEV0717A46` provides the stable AST evidence method for HSSL-G071. Durable cache-scope receipts bind plan, protocol, run, variant, split, mode, requested configuration, pinned environment, run contract, namespace, and canonical cache root. Symlink escapes fail before backend invocation.
- `benchmarks.logic_pipeline.runner.validate_cache_isolation` requires a complete cold/warm matrix with unique five-dimensional `CacheScope` namespaces and one pinned environment. It rejects route or requested/effective backend, model, and solver drift before computing a cache comparison receipt.
- The versioned schedule uses seed-ranked blocks and a seed-ranked base arm permutation rotated by block ordinal. The plan constructor and comparison validator both prove that each arm's thermal position counts differ by at most one, while preserving exact global, block, within-block, and job ordering for immutable resume.
- `tests/integration/benchmarks/logic_pipeline/test_resource_bounds.py` covers singleton/shared model identity, incompatible model oversubscription, queue delay, distinct solver and kernel capacity, cancellation wakeup, process-tree cleanup, stage resource lanes, and configured zero-solver enforcement.
- `tests/integration/benchmarks/logic_pipeline/test_cache_isolation.py` covers scope receipts and namespaces, pinned environment comparison, backend drift rejection, cold/warm separation, counterbalanced seeded order, immutable resume, and cache-root symlink escape.

## Objective and backlog alignment

HSSL-G071 and HSSL-G072 remain the smallest useful children of HSSL-G070: cache/backend/thermal comparison eligibility and resource/process enforcement have different contracts and focused validators, but share the frozen plan, execution order, and environment boundary. No smaller child goals or additional output refinements are needed.

The packet aggregate is implemented by HSSL-BENCH-003 and covers sibling tasks HSSL-BENCH-007 and HSSL-BENCH-009 with completion propagation. Generated todo-vector, objective-bundle, and task-status metadata were not manually edited. The supervisor can reconcile both missing evidence terms from the AST symbols, objective-heap contracts, this discovery receipt, and the focused validation commands.

## Validation

Required command:

```text
python -m pytest tests/integration/benchmarks/logic_pipeline/test_resource_bounds.py -q
```

Result: passed, 6 tests.

Packet sibling and regression validation:

- `python -m pytest tests/integration/benchmarks/logic_pipeline/test_cache_isolation.py -q`: passed, 6 tests.
- `python -m pytest tests/integration/benchmarks/logic_pipeline/test_runner.py -q`: passed, 11 tests.
- Complete logic-pipeline integration suite: 109 passed and 7 frozen A0 baseline tests failed because the current worktree's submodule gitlinks differ from the immutable baseline manifest. The failures all originate in `runner._validate_source_snapshot` before the changed ablation/cache/resource paths execute.
- Python bytecode compilation and repository whitespace checks: passed.
