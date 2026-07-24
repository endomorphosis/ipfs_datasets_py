# HSSL-BENCH-016 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-016
Goal: HSSL-G034 — Integrate Leanstral proof synthesis and bounded repair
Missing evidence: HSSLEV0342A4C
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-016-objective-gap-81ee0a557042.md`
Source fingerprint: `81ee0a557042d0d26b0e608a6da8ba0f2b3c908e`

## Evidence

- `benchmarks.logic_pipeline.adapters.HSSLEV0342A4C` is the stable AST evidence symbol for the Leanstral synthesis and bounded-repair objective.
- `LeanstralAdapter` resolves the supervisor-owned local `LeanstralProofProvider` lazily, so importing the benchmark never starts a model service or changes production routing. An injected handler/provider follows the same strict boundary for deterministic tests and offline benchmark runs.
- Every request binds exactly one safe `obligation_id`, a bounded prompt or context capsule, the model resource class, and a fixed `max_repair_attempts: 1`. A repair request must explicitly identify attempt 1 and carry a bounded failed draft plus failure diagnostic; attempt 2 is rejected before backend invocation.
- Provider drafts require the pinned Leanstral draft schema, artifact identity, draft text, matching obligation IDs, and the model resource lane. Unknown fields, malformed schemas, digest mismatches, `sorry`/`admit`/`axiom`/`unsafe` constructs, and claims of verification or authority fail closed with `LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT`.
- Successful stage data is a content-addressed `leanstral-evidence.v1` record containing synthesis/repair mode, repair count, trust flags fixed to unverified, and distinct `model`/`kernel` resource classes. `StageOutput.kernel_accepted` and kernel receipts remain false; only the separate kernel adapter can establish authority.
- Timeout and provider rejection are retained as failed stage outcomes, while missing provider/router dependencies are explicit `CAPABILITY_UNAVAILABLE` outcomes. No backend result is silently substituted with another benchmark arm.

## Validation

Command: `python -m pytest tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py -q`

Result: 8 focused integration tests passed. Coverage includes successful synthesis, one bounded repair with failure-context preservation, malformed/forbidden/authority-claim rejection, timeout, unavailable backend, fixed-obligation enforcement, and repair-bound enforcement. Draft records round-trip through the versioned stage contract.

## Backlog alignment

HSSL-G034 is already bounded by the adapter output and focused integration validation; no smaller child goal is required. The objective heap now records the evidence implementation and repair contract. Generated supervisor todo/vector/task state remains supervisor-owned and was not edited manually.
