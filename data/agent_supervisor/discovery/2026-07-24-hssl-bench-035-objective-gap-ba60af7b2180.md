# HSSL-BENCH-035 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-035
Goal: HSSL-G114 — Make every frozen arm execute its real bounded stage graph
Missing evidence: HSSLEV1142E95
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-24-hssl-bench-035-objective-gap-ba60af7b2180.md`
Source fingerprint: `ba60af7b2180a8578fbd1024e7aaac09eb66342d`
Todo vector: `f48d517c93158196`
Merge key: `ca30272ca1fb5952`
Merge family: `objective/HSSL-G114`
Work scope: `goal_subgoal_multi_evidence_batch`

## Evidence

- `benchmarks.logic_pipeline.runtime.HSSLEV1142E95` is the stable AST-verifiable code receipt.
- `runtime.build_live_runtime` builds exact per-arm adapters from the frozen capability inventory. Available Hammer stages cannot remain handlerless; built-in live spaCy, SyMAI/router, Leanstral, current-compiler, and native-kernel paths are lazy and identity-bound. Unavailable capabilities remain explicit under the requested arm.
- `adapters.StageArtifact`, `StageRequest.upstream_artifacts`, and the two-phase `StageAdapter.invoke`/`record` boundary carry bounded typed payloads and content digests through the real invocation graph while retaining the canonical durable record order.
- `ablation.execute_ablation` enforces the ambiguity gate, proof-failure fallback, and preregistered proof order across A0-A12/S1. It records zero-call policy decisions, keeps S1 non-authoritative, uses one plan-owned run contract per arm/cache coordinate, and retains canonical provenance.
- `runtime.compile_reviewed_obligation` produces deterministic, target-bound runnable Lean templates. `NativeKernelRunner` uses the repository managed-process supervisor and can issue proof authority only from an independent, bounded, reaped native-kernel receipt.
- `tests/integration/benchmarks/logic_pipeline/test_live_runtime.py` covers capability binding, unavailable behavior, obligation compilation, kernel receipts, and lifecycle ownership.
- `tests/integration/benchmarks/logic_pipeline/test_ablation_dataflow.py` parameterizes every arm, both ambiguity decisions, proof fallback suppression, Leanstral-first execution, canonical persistence, typed downstream artifacts, unique contracts, and S1 authority withholding.

## Validation

Command:

```text
python -m pytest tests/integration/benchmarks/logic_pipeline/test_live_runtime.py tests/integration/benchmarks/logic_pipeline/test_ablation_dataflow.py tests/integration/benchmarks/logic_pipeline/test_kernel_bound_results.py tests/integration/benchmarks/logic_pipeline/test_hammer_adapter.py tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py -q
```

Result: `46 passed in 2.71s`.

## Backlog alignment

HSSL-G114 remains a single cohesive runtime trust-boundary goal; no smaller
child goal is required. The objective heap now names the implementation and
validation receipts for HSSLEV1142E95. The generated todo vector, objective
bundle status, and external supervisor metadata remain untouched so the
supervisor can reconcile them from this receipt and the AST marker.
