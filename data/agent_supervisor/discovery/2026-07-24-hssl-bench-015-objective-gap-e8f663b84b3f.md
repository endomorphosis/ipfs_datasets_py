# HSSL-BENCH-015 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-015
Goal: HSSL-G033 — Integrate Hammer request, portfolio, and reconstruction records
Missing evidence: HSSLEV0335D9B
Source finding: `2026-07-23-hssl-bench-015-objective-gap-e8f663b84b3f.md`

## Evidence

- `benchmarks.logic_pipeline.adapters.HSSLEV0335D9B` is the stable AST evidence symbol for the goal.
- `HammerAdapter` lazily consumes the existing Hammer contracts rather than duplicating them: `HammerRequest`, `PortfolioRunResult`, `ProofCandidateRecord`, `ReconstructionRecord`, `EnvironmentLockRecord`, and `NormalizedEvidence`.
- Every successful Hammer stage record contains a versioned, content-addressed `hammer-evidence.v1` payload with request, portfolio, normalized evidence, candidate, reconstruction, and environment-lock records.
- The adapter rejects portfolio attempts from another request, candidates from another request or unknown attempt, normalized evidence from another attempt, reconstruction/candidate mismatches, and reconstruction/environment-lock mismatches.
- Executed portfolio attempts must be allowlisted by the request policy, stay within its timeout budget, and not use a denied network; learned premise selection and LLM ranking are restricted to the preregistered A10 and A11 variants.
- Solver and reconstruction records remain data on the Hammer stage. `StageOutput.kernel_accepted` is never set by the Hammer adapter; final benchmark verification remains kernel-stage-only.
- Missing Hammer handlers remain an explicit `CAPABILITY_UNAVAILABLE` stage outcome.

## Validation

Command: `python -m pytest tests/integration/benchmarks/logic_pipeline/test_hammer_adapter.py -q`

Coverage includes native and serialized record paths, accepted and rejected reconstruction evidence, unavailable-handler behavior, stable round-trip serialization, and adversarial request/candidate/reconstruction identity mismatches.

## Backlog alignment

The gap is fully covered by the existing HSSL-G033 aggregate work item and does not require a smaller child goal. The objective heap section for HSSL-G033 records the implementation contract and focused validation; generated supervisor todo/vector state remains supervisor-owned and is not manually edited.
