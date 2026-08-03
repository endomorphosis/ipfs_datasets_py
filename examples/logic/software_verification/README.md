# Software Verification Runnable Examples

**Interface:** `RunnableVerificationExamples@1`
**Companion report interface:** `LiveReadinessReport@1`
**Goal:** FVT-G013 / FVT-021 — replace manifest-only examples and synthetic readiness claims.

## Purpose

This tree is the source-bound inventory for end-to-end software-verification
exemplars. The checked-in `manifest.json` lists seven deterministic lanes. Each
lane binds a source identity, positive and negative cases, optional tools, and
a declared assurance ceiling.

Historical gap (closed by FVT-021):

- Manifest paths were referenced but not materialised for execution.
- Negative cases used **injected** counterexample witnesses.
- Readiness claims were sometimes hard-coded distributions rather than
  **actual run receipts**.

This README and the integration test
`ipfs_datasets_py/tests/integration/logic/software_verification/test_runnable_examples.py`
require:

1. Every manifest source text is present, materialisable, and exercised.
2. Negative variants **generate** witnesses (solver models, monitor verdicts,
   policy denials derived from source semantics) rather than treating the
   manifest `counterexample` block as sole authority.
3. Positive variants produce **current** public-API receipts / pipeline
   receipts with stable run identities (`request_id`, receipt ids, content
   digests).
4. The live report
   `docs/architecture/formal_verification_live_example_report.json` cites those
   identities and separates evidence classes.

## Layout

| Path | Role |
|------|------|
| `manifest.json` | Lane inventory (`SoftwareVerificationExamples@1`) with embedded source text and case statements |
| `README.md` | This document — runnable contract and evidence-class policy |
| *(materialised)* `sources/*` | Written by the integration test from manifest text into a temporary workspace; path strings in the manifest are the identity anchors |

On-disk `sources/` files under this directory are optional. Authoritative source
bodies for offline CI are the `source.text` fields in `manifest.json`. The
runnable test always materialises them before execution so path-based identity
and content digests stay aligned.

## Lanes

| Lane id | Goal facet | Declared assurance | Optional tools |
|---------|------------|--------------------|----------------|
| `contracts_resources` | contracts/resources | bounded | z3, cvc5 |
| `heap_ownership` | heap ownership | bounded | z3 |
| `concurrent_workflows` | concurrent workflows | bounded | tlc, apalache |
| `authorization` | authorization | authorization | — |
| `cryptographic_protocols` | cryptographic protocols | protocol | tamarin, proverif |
| `noninterference` | noninterference | hyperproperty | — |
| `runtime_temporal_monitoring` | runtime temporal monitoring | monitor | — |

Each lane must declare at least one `positive` and one `negative` case.

## Production entrypoints

Examples must run through production surfaces, not private test doubles:

| Surface | Module | Operations used |
|---------|--------|-----------------|
| Public verification API | `ipfs_datasets_py.logic.verification_api` | `compile_verification_artifact`, `check`, `monitor`, `run_portfolio`, `explain_counterexample`, `verify_receipt`, `list_providers` |
| Source → VC → SMT pipeline | `ipfs_datasets_py.logic.software_verification.pipeline` | `SourceToVerificationPipeline.run` (contracts lane live generation) |
| Source adapter | `ipfs_datasets_py.logic.software_verification.source_adapters` | `adapt_source_to_software_verification` |

Optional external tools degrade to explicit `unavailable` / `unsupported` /
`error` statuses. Missing tools must never become silent success.

## Evidence classes (`LiveReadinessReport@1`)

Every case outcome in the live report is labeled with exactly one primary
evidence class:

| Class | Meaning | Production-readiness claim? |
|-------|---------|-------------------------------|
| `fixture` | Deterministic offline structure (manifest, digests, IR shape) without claiming a live tool outcome | **No** |
| `simulated` | Interpreter or API path that evaluates a derived witness without an external prover binary | **No** (bounded / monitor / policy only as declared) |
| `live` | Bounded live probe or dual-solver pipeline produced a model/proof on this machine | **Not automatically production-certified** — still requires hermetic toolchain certification (FVT-006 / FVT-030) |
| `skipped` | Case intentionally not executed under current bounds (e.g. heavy optional tool not requested) | **No** |
| `unsupported` | Source or construct is outside the supported fragment; fail-closed diagnostic retained | **No** |
| `unavailable` | Required tool or runtime dependency missing or not probeable offline | **No** |

**Policy:** synthetic fixtures remain useful for unit determinism, but they are
never production-readiness claims. Offline fixture success does not imply live
or certified status.

## Generation rules (anti-injection)

- **Positive program variants** lower through the source→VC→SMT pipeline (or
  compile/portfolio) and record the resulting receipt ids / digests.
- **Negative program variants** apply a source mutation (for example removing a
  budget guard) and let solvers **emit** a model. The test fails if only a
  hand-written witness is present and no generation path was exercised.
- **Non-program lanes** derive denial / race / leak / violation structures from
  the materialised source semantics (policy JSON, formula, observations), then
  pass those **generated** structures through `explain_counterexample` or
  `monitor`. Manifest `counterexample` blocks are documentation hints, not the
  sole evidence.

## Live report

Path: `docs/architecture/formal_verification_live_example_report.json`

Schema: `formal-verification-live-example-report/v1`
Interface: `LiveReadinessReport@1`

Required fields (non-exhaustive):

- `run_id` — content-addressed identity of the report corpus
- `goal_id` / `task_id` — `FVT-G013` / `FVT-021`
- `manifest` — path + content digest
- `evidence_class_vocabulary` — the six classes above
- `lanes[]` / `cases[]` — per-case `run_identity`, `evidence_class`,
  `result_status`, `generated_witness` flag, receipt / request ids
- `summary` — counts by evidence class; never a hard-coded readiness percentage
- `production_readiness_claims` — explicit empty or false for fixture/simulated

## How to run

```bash
python -m pytest \
  ipfs_datasets_py/tests/integration/logic/software_verification/test_runnable_examples.py -q
```

The suite is offline-first: it never installs tools or opens the network.
When z3 and cvc5 are on `PATH`, the contracts lane records `live` generation;
otherwise those solver cases are labeled `unavailable` without failing the
suite’s structural gates.

Optional rewrite of the checked-in report from a fresh local run:

```bash
FVT_021_WRITE_LIVE_REPORT=1 python -m pytest \
  ipfs_datasets_py/tests/integration/logic/software_verification/test_runnable_examples.py -q
```

## Conflict policy

- Own this example tree documentation, the runnable integration test, and the
  live report.
- Retain small deterministic fixtures elsewhere for unit tests, but **remove
  them from production-readiness claims**.
- Do not change provider behavior solely to fit fixtures.

## Related artifacts

- Objective heap: `docs/architecture/formal_verification_tactician_readiness.objectives.md` (FVT-G013)
- Readiness baseline ladder: `docs/architecture/formal_verification_readiness_baseline.json`
- Vertical slice: `ipfs_datasets_py/tests/integration/logic/software_verification/test_source_vc_smt_pipeline.py`
- Manifest binding (LFV era): `ipfs_datasets_py/tests/integration/logic/test_software_verification_examples.py`
