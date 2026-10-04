# Hammer, SyMAI, spaCy, and Leanstral Benchmark Objective Heap

This is machine-ingestible planning state for
`ipfs_accelerate_py.agent_supervisor.objective_daemon`. Goal completion requires
the named evidence receipt and the validation command; model confidence alone
is never completion evidence.

> **REVISION-2 OPERATIONAL NO-GO — 2026-07-26.** HSSL-G231 and HSSL-G240
> now have bounded local implementation markers backed by source-safe
> integration and adversarial validation. Those markers are implementation
> evidence only: they do not satisfy the externally governed operational
> joins. HSSL-G201, HSSL-G202, HSSL-G203, HSSL-G212, HSSL-G220, HSSL-G232,
> HSSL-G241, HSSL-G242, and HSSL-G243 have no accepted operational completion
> authority. Do not run a
> pilot/development matrix, open a benchmark source/label/manifest/proof
> obligation, request replacement-holdout custody, or publish a revision-2
> decision. Only explicitly source-safe synthetic tests, non-corpus component
> smokes, implementation-source review, and supervisor dry-run reconciliation
> are currently permitted. Revision-1 validation commands are historical
> reproduction instructions only; future commands that may touch benchmark
> inputs become eligible only through the exact external gate chain declared
> below.

## HSSL-G009 Reject empty AST symbols as objective evidence

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G000
- Fib priority: 0
- Track: benchmark-protocol
- Priority: P0
- Bundle: objective/hssl/supervisor-compatibility
- Goal: Prevent empty AST symbols from satisfying every objective evidence term before the benchmark goal heap is compiled into executable work.
- Evidence: HSSLEV0097B20
- Outputs: ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/objective_graph.py, ipfs_accelerate_py/test/api/test_agent_supervisor_objective_graph.py
- Validation: PYTHONPATH=ipfs_accelerate_py python -m pytest ipfs_accelerate_py/test/api/test_agent_supervisor_objective_graph.py -k empty_symbol -q
- Acceptance: Empty and whitespace-only symbols are excluded from fuzzy AST evidence matching, a unique missing evidence marker produces a finding, and existing exact and nonempty AST evidence behavior remains covered.
- Gap task: Add the smallest fail-closed evidence-index fix and regression test in the isolated ipfs_accelerate_py submodule worktree, then rerun objective compilation without forced goals.
- Refinement depth: 1

## HSSL-G000 Establish the isolated benchmark package and execution skeleton

- Status: active
- Goal completion schema version: 1
- Parent:
- Fib priority: 0
- Track: benchmark-foundation
- Priority: P0
- Bundle: objective/hssl/foundation
- Goal: Create the non-production benchmark package skeleton, smoke contract, and run-scoped execution defaults without changing production routing.
- Evidence: HSSLEV0009A31
- Outputs: benchmarks/logic_pipeline/__init__.py, tests/unit/benchmarks/logic_pipeline/test_package.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_package.py -q
- Acceptance: The package imports when optional components are absent, all state and output defaults are run-scoped, the smoke manifest is deterministic, and no production routing default changes.
- Gap task: Scaffold the isolated benchmark package and its deterministic smoke test.
- Refinement depth: 0
- Conflict policy: keep benchmark changes isolated; require review before merging any production routing change
- Evidence implementation: `benchmarks.logic_pipeline.HSSLEV0009A31` binds this goal to the dependency-free execution contract; `RunPaths`, `ExecutionDefaults`, and the canonical smoke-manifest helpers implement it.
- Foundation safety: A required validated run id scopes cache, corpus, objective bundles, receipts, results, state, logs, and worktrees; defaults are offline, shadow-only, non-promoting, and side-effect-free at import.
- Backlog alignment: The original two code/test outputs and validation command are sufficient for this bounded root goal, so no child goal or downstream dependency change is required.

## HSSL-G010 Freeze the benchmark protocol and safety invariants

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G000, HSSL-G009
- Fib priority: 1
- Track: benchmark-protocol
- Priority: P0
- Bundle: objective/hssl/protocol
- Goal: Preregister hypotheses, variants, metrics, thresholds, exclusion rules, trust boundaries, and stop conditions before pilot results are inspected.
- Evidence: HSSLEV0103C72
- Outputs: benchmarks/logic_pipeline/README.md, benchmarks/logic_pipeline/contracts.py, tests/unit/benchmarks/logic_pipeline
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_contracts.py -q
- Acceptance: The protocol defines paired variants, kernel-only verification, zero-tolerance invalid controls, cache isolation, holdout rules, material improvement thresholds, and explicit infrastructure-failure handling.
- Gap task: Implement and validate the preregistered protocol and versioned record contracts.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.contracts.HSSLEV0103C72` binds this goal to the dependency-free frozen protocol; immutable protocol, run, cache, outcome, pairing, stop, and candidate-gate records enforce the preregistration at deserialization and evaluation boundaries.
- Frozen protocol: Revision 1 covers H1-H7, paired A0-A12 arms and the non-candidate S1 diagnostic, metric registries, kernel-only trust, zero invalid-control tolerance, run/variant/split/cache-mode isolation, audited no-tuning holdout access, explicit exclusions and infrastructure missingness, final numeric materiality gates, and bounded stop conditions. Its canonical SHA-256 is `a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3`.
- Backlog alignment: The existing HSSL-G011, HSSL-G012, and HSSL-G020 descendants already isolate worktree safety, capability identity, and corpus construction. HSSL-G010 remains one cohesive protocol work item, so no child goal, parent edge, output, or generated supervisor task-state change is required.

## HSSL-G011 Prove isolated worktree and state-root safety

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G010
- Fib priority: 1
- Track: benchmark-protocol
- Priority: P0
- Bundle: objective/hssl/protocol
- Goal: Guarantee that benchmark creation, supervisor lanes, caches, receipts, and results cannot clean, reset, overwrite, or merge the active checkout.
- Evidence: HSSLEV0118D14
- Outputs: benchmarks/logic_pipeline/capabilities.py, tests/integration/benchmarks/logic_pipeline
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_worktree_isolation.py -q
- Acceptance: Tests use a disposable repository to prove pinned-base worktree creation, run-specific state roots, no active-checkout mutations, no automatic merge, and explicit submodule commit capture.
- Gap task: Add the worktree isolation contract, adversarial tests, and a machine-readable safety receipt.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.capabilities.HSSLEV0118D14` binds this goal to the executable worktree-safety contract; pinned worktree preparation, immutable repository snapshots, and canonical safety receipts make the isolation claim machine-verifiable.
- Safety contract: Preparation resolves and records an exact base commit, creates only a detached run-scoped worktree, keeps cache, receipt, result, supervisor, and other mutable state below the selected run root, captures explicit submodule gitlink commits, and verifies that the active checkout's HEAD, branch, status, and contents are unchanged. Active-checkout targets, overlapping or escaping state roots, automatic merge, and destructive Git operations fail closed.
- Backlog alignment: HSSL-G011 and HSSL-G012 are already the two bounded work items in `goal_packet/benchmark_protocol/benchmarks/e434c88200e1` and share the cohesive `capabilities.py` output. No child goal, parent edge, or output refinement is needed; successful HSSL-BENCH-001 packet validation propagates to HSSL-BENCH-004 and HSSL-BENCH-005 without manually changing generated supervisor todo/vector state.

## HSSL-G012 Inventory runtime capabilities and identities

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G010
- Fib priority: 2
- Track: benchmark-protocol
- Priority: P0
- Bundle: objective/hssl/protocol
- Goal: Detect and record spaCy pipelines, SyMAI configuration, llm_router providers, Hammer solvers, Leanstral model service, Lean toolchain, cache backend, and resource scheduler before running variants.
- Evidence: HSSLEV0125F83
- Outputs: benchmarks/logic_pipeline/capabilities.py, tests/unit/benchmarks/logic_pipeline/test_capabilities.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_capabilities.py -q
- Acceptance: Every optional capability is available, unavailable, or degraded with provenance; no missing tool silently becomes a different benchmark variant.
- Gap task: Implement fail-closed capability probing and environment identity capture.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.capabilities.HSSLEV0125F83` binds this goal to the versioned capability and environment inventory; canonical records preserve requested and effective identities, probe provenance, and a replayable digest before any variant runs.
- Capability contract: The preflight records spaCy pipelines, SyMAI configuration, llm_router providers, Hammer solvers, the Leanstral model service, the Lean toolchain, the cache backend, and the resource scheduler as `available`, `unavailable`, or `degraded`. Probe failures and fallbacks remain explicit, secret values are not serialized, and a missing or degraded requirement makes the requested variant ineligible instead of silently selecting another effective arm.
- Backlog alignment: HSSL-G012 remains the existing capability member of the HSSL-G011/HSSL-G012 protocol packet, with its unit contract and shared implementation already represented by HSSL-BENCH-001 and HSSL-BENCH-005. No child goal or generated backlog edit is required; aggregate completion remains validation-driven and propagates through the packet work order.

## HSSL-G020 Build the reviewed and immutable benchmark corpus

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G010
- Fib priority: 3
- Track: benchmark-corpus
- Priority: P0
- Bundle: objective/hssl/corpus
- Goal: Create a representative, independently reviewable pilot, development, and holdout corpus for semantic conversion and formal proof.
- Evidence: HSSLEV0201B64
- Outputs: tests/fixtures/logic_pipeline_benchmark/corpus.jsonl, tests/fixtures/logic_pipeline_benchmark/manifest.json, benchmarks/logic_pipeline/cases.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_cases.py -q
- Acceptance: Every case has a stable ID, split, stratum, source digest, expected class, reviewed semantic target, proof obligation where applicable, and provenance; the manifest binds order and contents.
- Gap task: Assemble, validate, review, and digest the benchmark corpus without using model output as ground truth.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.cases.HSSLEV0201B64` binds this goal to the dependency-free reviewed-corpus contract; strict, immutable case, review, manifest, and loaded-corpus records make the evidence executable rather than prose-only.
- Corpus contract: Corpus revision 1 contains 30 canonical cases, with ten each in pilot, development, and holdout, spanning ten semantic/proof strata and every expected class. Stable unique IDs, exact source SHA-256 values, nonempty reviewed semantic IR, class-appropriate theorem or countermodel obligations, required predicates/entities, negative-control labels, and explicit provenance are validated before use. Two distinct reviewer roles must approve each target, model output and model-generated ground truth are forbidden, and nested records are deeply immutable. The canonical manifest identity is `58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26`; it binds protocol revision, byte-exact corpus order/content (`a2720cee073bfe4221594c5b29d8a4557865f272f4d2c2c3553dfeab74c03509`), every case and source digest, coverage counts, and the reviewed semantic targets (`9a1747aac8ab7393147795b7f756318a67f66b6f4eedd6ed368b0337c5e46932`). Strict loading rejects duplicate keys, noncanonical JSON, field drift, reorder, or tampering.
- Backlog alignment: HSSL-G020 remains one bounded core-corpus work item. Existing children HSSL-G021, HSSL-G022, and HSSL-G023 already isolate fixture import, expanded adversarial controls, and leakage/split-integrity auditing, so no child goal, parent edge, output, or generated todo/vector status change is needed; completion remains validation-driven.

## HSSL-G021 Reuse existing regression and ambiguity fixtures

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G020
- Fib priority: 2
- Track: benchmark-corpus
- Priority: P1
- Bundle: objective/hssl/corpus
- Goal: Import suitable Legal IR ambiguity packets, FOL/deontic/modal fixtures, Hammer cases, and Leanstral regressions through provenance-preserving adapters.
- Evidence: HSSLEV0217E25
- Outputs: tests/fixtures/logic_pipeline_benchmark, tests/unit/benchmarks/logic_pipeline/test_fixture_import.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_fixture_import.py -q
- Acceptance: Imported cases retain their original identifiers or source references, receive no model-generated expected result, and preserve positive and negative coverage.
- Gap task: Add deterministic fixture importers and provenance checks.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.fixture_import.HSSLEV0217E25` binds this goal to the executable fixture-import contract; strict import entries, a canonical manifest, and a deeply immutable loaded fixture set make provenance-preserving reuse deterministic and machine-verifiable.
- Fixture-import contract: Manifest schema `ipfs-datasets.logic-pipeline-benchmark.fixture-import-manifest.v1` freezes nine imports: two Legal IR ambiguity packets, two FOL/deontic/modal conformance cases, three Hammer golden/poisoned/reconstruction cases, and two Leanstral modality mutations, with five positive and four negative outcomes. Every entry preserves its original identifier, source path and selector, complete source payload, exact source-byte and canonical-record digests, `existing_fixture` expectation origin, and an explicit false model-generated attestation. Strict loading rejects schema drift, duplicate or ambiguous identifiers, path traversal, model provenance, source/provenance changes, coverage/count drift, and manifest/content tampering.
- Backlog alignment: HSSL-G021 is the fixture-reuse member of `goal_packet/benchmark_corpus/general/919ae362bc61`; its shared fixture directory is intentionally implemented alongside HSSL-G022's negative controls by aggregate task HSSL-BENCH-002. Successful validation of the packet's import and adversarial contracts propagates to covered sibling HSSL-BENCH-008 without manually changing generated todo/vector metadata. The goal remains active for supervisor reconciliation, and no child goal or graph refinement is needed.

## HSSL-G022 Add adversarial and negative proof controls

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G020
- Fib priority: 3
- Track: benchmark-corpus
- Priority: P0
- Bundle: objective/hssl/corpus
- Goal: Ensure invalid, contradictory, unsupported, prompt-like, copied, sorry-bearing, and admit-bearing inputs can never appear as verified improvements.
- Evidence: HSSLEV0224A96
- Outputs: tests/fixtures/logic_pipeline_benchmark, tests/integration/benchmarks/logic_pipeline/test_adversarial_controls.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_adversarial_controls.py -q
- Acceptance: All adversarial controls fail closed or receive their expected non-verified class across deterministic contract tests.
- Gap task: Create and independently validate negative controls for every trust boundary.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.adversarial.HSSLEV0224A96` binds this goal to the executable adversarial-control contract; immutable controls, a content-addressed control suite, deterministic candidate classification, and a fail-closed candidate gate turn every named negative class into testable evidence.
- Adversarial-control contract: The frozen suite contains exactly one independently identified control for each of `invalid`, `contradictory`, `unsupported`, `prompt_like`, `copied`, `sorry_bearing`, and `admit_bearing`. Canonical JSONL and its manifest bind order, content, reviewed rationale, complete kind coverage, and all record/file digests; the gate binds each control to an expected rejected or safety-incident disposition. Duplicate keys, unknown fields, noncanonical bytes, reordering, count drift, digest changes, and coverage tampering fail closed. Every control is ineligible for a verified improvement. If any adversarial candidate is nevertheless claimed kernel-verified, the gate emits an `INVALID_CONTROL_VERIFIED` safety incident rather than eligibility; only a benign candidate with an accepted kernel receipt can pass.
- Backlog alignment: HSSL-G022 is the P0 anchor of `goal_packet/benchmark_corpus/general/919ae362bc61`; aggregate HSSL-BENCH-002 owns the cohesive HSSL-G021/HSSL-G022 change and covers sibling HSSL-BENCH-006. Packet completion propagates only after both focused validations succeed, while all goal statuses remain active for supervisor reconciliation. No child goal, parent edge, or manual edit to generated todo/vector metadata is required.

## HSSL-G023 Freeze split integrity and leakage checks

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G020
- Fib priority: 5
- Track: benchmark-corpus
- Priority: P0
- Bundle: objective/hssl/corpus
- Goal: Prevent duplicate, near-duplicate, cache, prompt, and tuning leakage across pilot, development, and holdout splits.
- Evidence: HSSLEV0232D57
- Outputs: benchmarks/logic_pipeline/cases.py, tests/unit/benchmarks/logic_pipeline/test_holdout_integrity.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_holdout_integrity.py -q
- Acceptance: Exact and normalized duplicate checks pass, split digests are frozen, and holdout access is auditable.
- Gap task: Implement split-integrity validation and a frozen holdout manifest.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.cases.HSSLEV0232D57` binds this goal to executable split and holdout integrity. Frozen, strict split manifests, cross-split leakage validation, prompt screening, and immutable holdout-access audits turn the objective into machine-verifiable evidence.
- Split/leakage contract: Revision 1 normalizes source text with Unicode NFKC, case folding, and punctuation/whitespace collapse; rejects exact, normalized, provenance, and token-trigram near copies across splits at the frozen `0.8` Jaccard threshold; and requires holdout prompt exposure to remain `none`. The pilot (`a050371dae1248deecfb17f2d9e610124c6e493a1a227ec3c161008891ce1881`), development (`530860019b164c9750083ec5affd6ae71202b695c8c8042400d0f02488436b74`), holdout (`c7b969ed19a1248143740068e2853ca6132ba3d65dfeec4133e37fad55dbab4a`), and aggregate split-integrity (`dd68177636a3db87752de54399ed8f066d5fdefe568649d9551bb29a0fb529d0`) identities bind the reviewed corpus manifest, ordered case membership, exact case/source digests, and normalized sources. Each access receipt composes with the preregistered run contract so run, variant, holdout split, cold/warm cache, frozen configuration/prompts/policy/model identities/thresholds, accessed cases, prompt-example fingerprints, audit ID, and no-tuning state are content-addressed together.
- Backlog alignment: HSSL-G023 remains one cohesive bounded child of HSSL-G020. Its existing implementation/test outputs and focused validation cover the gap, so no child goal, parent edge, output refinement, or manual generated todo/vector status change is needed; the goal remains active for supervisor reconciliation from validated evidence.

## HSSL-G030 Implement versioned stage adapters and telemetry

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G012
- Fib priority: 5
- Track: benchmark-adapters
- Priority: P0
- Bundle: objective/hssl/adapters
- Goal: Expose the current compiler, spaCy, SyMAI, Hammer, Leanstral, and kernel paths through versioned benchmark records without changing production behavior.
- Evidence: HSSLEV0306C18
- Outputs: benchmarks/logic_pipeline/adapters.py, benchmarks/logic_pipeline/contracts.py, tests/unit/benchmarks/logic_pipeline
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_adapters.py tests/unit/benchmarks/logic_pipeline/test_contracts.py -q
- Acceptance: Each stage emits bounded, provenance-bearing data; unverified stages cannot serialize a verified final status; the current baseline route remains behaviorally unchanged.
- Gap task: Add thin adapters, strict contracts, and deterministic telemetry serialization.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.adapters.HSSLEV0306C18` binds this goal to the dependency-free adapter boundary; `StageRequest`, six versioned stage adapters, immutable provenance/telemetry records, content-addressed stage records, and kernel-bound case results make the evidence executable without importing or changing any production route.
- Adapter contract: Compiler, spaCy, SyMAI, Hammer, Leanstral, and kernel stages use the stable `StageName` vocabulary and adapter version `1`. Every invocation records requested/effective identity, input and upstream digests, environment identity when available, bounded output, deterministic telemetry serialization, explicit unavailable/failure states, and a stage-bound resource lane (`cpu`, `model`, `solver`, or `kernel`). Only a successful kernel stage with an accepted native-kernel receipt can produce a verified case result; model, solver, missing-backend, and non-kernel receipt claims fail closed.
- Baseline safety: `build_default_adapters()` performs no optional imports and supplies no handlers, so the existing production route remains untouched. Backend-specific children HSSL-G031 through HSSL-G035 can inject their existing implementations into this boundary without changing the record contract.
- Backlog alignment: HSSL-G030 remains one bounded parent adapter work item. Its foundational contract is implemented here; the existing child goals remain separate for spaCy, SyMAI, Hammer, Leanstral, and receipt-specific integrations, so no new child goal or generated todo/vector edit is required.

## HSSL-G031 Integrate spaCy as reproducible linguistic evidence

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G030
- Fib priority: 3
- Track: benchmark-adapters
- Priority: P1
- Bundle: objective/hssl/adapters-spacy
- Goal: Capture tokens, sentences, lemmas, dependencies, entities, semantic roles, and modal cues using the existing spaCy modal and SRL paths while distinguishing the full requested model, blank-model fallback, and regex/legal parser.
- Evidence: HSSLEV0310F79
- Outputs: benchmarks/logic_pipeline/adapters.py, tests/unit/benchmarks/logic_pipeline/test_spacy_adapter.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_spacy_adapter.py -q
- Acceptance: Output is deterministic for a fixed pipeline, records requested and effective model identity and fallback use, treats an unavailable requested full model as unavailable rather than successful fallback, has a stable digest, and makes no semantic-proof claim.
- Gap task: Implement and test the spaCy evidence adapter over available and missing-model conditions.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.adapters.HSSLEV0310F79` binds this goal to the reproducible linguistic-evidence boundary. `SPACY_EVIDENCE_SCHEMA`, `SpacyAdapterMode`, `SpacyAdapterConfig`, and the configured `SpacyAdapter` capture document identity, tokens and lemmas, sentence spans, dependencies, entities, semantic-role frames, legal modal cues/IR, execution identity, and assurance from the existing spaCy modal, SRL, and regex/legal-parser paths in a bounded, content-addressed stage payload.
- Linguistic evidence contract: The adapter records the requested and effective identities, spaCy/model versions, pipeline components, and a model-metadata digest, and pins the execution mode to `full_model`, `blank_model`, or `regex_legal`. Full-model mode refuses spaCy's implicit blank fallback: a missing requested model is `unavailable`, never a successful blank or regex result. The other modes are deliberate controls with explicit identities. Fixed inputs and a fixed effective backend serialize deterministically despite non-deterministic identifiers in upstream SRL objects; every mode remains descriptive evidence, never a semantic proof or kernel-acceptance claim.
- Backlog alignment: HSSL-G031 remains one cohesive, bounded child of HSSL-G030. Its adapter output and focused unit validation cover HSSLEV0310F79 without another child goal; generated supervisor todo/vector/task state remains supervisor-owned and is not manually edited.

## HSSL-G032 Integrate SyMAI through the existing router

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G030
- Fib priority: 3
- Track: benchmark-adapters
- Priority: P1
- Bundle: objective/hssl/adapters-symai
- Goal: Run SymbolicAI/SyMAI semantic interpretation through the existing IPFS llm_router engine with strict contracts, bounded retries, and isolated cache namespaces.
- Evidence: HSSLEV0328B3A
- Outputs: benchmarks/logic_pipeline/adapters.py, tests/unit/benchmarks/logic_pipeline/test_symai_adapter.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_symai_adapter.py -q
- Acceptance: Import/configuration failures are explicit, recursive routing is rejected, structured output is validated, raw output is retained separately, and no second Leanstral server is started.
- Gap task: Implement and test the SyMAI adapter, including dry-run, cache, malformed-contract, and unavailable-package cases.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.adapters.HSSLEV0328B3A` binds this goal to the strict existing-router boundary. `SYMAI_EVIDENCE_SCHEMA`, `SymaiAdapterConfig`, and the configured `SymaiAdapter` execute the repository's `IPFSSyMAINeurosymbolicEngine`, which pins the existing `ipfs_datasets_py.llm_router` provider path and disables local-model fallback instead of creating another model manager or Leanstral service.
- SyMAI router contract: Every request derives its namespace from the frozen `CacheScope` across protocol, run, variant, split, and cold/warm mode; its cache key additionally binds case input, upstream records, provider, model, and dry-run state. The adapter rejects router re-entry before and after dispatch, caps retries and bytes, requires one exact JSON semantic contract, retains raw model text separately from validated candidate IR, records requested/effective router identity and telemetry, and denies every proof, kernel, verification, or authority claim. Missing packages or preflight configuration, router failures, and malformed contracts remain distinct explicit outcomes.
- Backlog alignment: HSSL-G032 remains one cohesive, bounded child of HSSL-G030. Its configured adapter, existing-engine extension, focused unit validation, and discovery receipt cover HSSLEV0328B3A without a smaller child goal; generated supervisor todo/vector/task state remains supervisor-owned and is not manually edited.

## HSSL-G033 Integrate Hammer request, portfolio, and reconstruction records

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G030
- Fib priority: 3
- Track: benchmark-adapters
- Priority: P0
- Bundle: objective/hssl/adapters-hammer
- Goal: Reuse Hammer premise selection, translation, bounded solver portfolio, normalization, reconstruction, and receipt contracts as the proof-search path.
- Evidence: HSSLEV0335D9B
- Outputs: benchmarks/logic_pipeline/adapters.py, tests/integration/benchmarks/logic_pipeline/test_hammer_adapter.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_hammer_adapter.py -q
- Acceptance: Solver evidence is untrusted, commands are allowlisted and bounded, candidate and request IDs match, learned or LLM ranking is opt-in by named variant, and only reconstruction with kernel acceptance can verify.
- Gap task: Implement a thin Hammer benchmark adapter and adversarial identity/trust tests.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.adapters.HSSLEV0335D9B` and `HammerAdapter` lazily reuse the native Hammer request, bounded portfolio, normalized evidence, proof-candidate, reconstruction, and environment-lock contracts. The adapter emits a content-addressed `hammer-evidence.v1` payload, rejects mixed request/attempt/candidate/reconstruction identities, enforces solver allowlists and request timeout/network budgets, restricts learned ranking to A10 and LLM ranking to A11, preserves serialized records, and never sets the benchmark stage's kernel authority bit from solver or reconstruction data.
- Hammer adapter contract: A handler must return `request` plus `portfolio`/`run_result`; candidate, reconstruction, environment lock, and normalized evidence are optional only where the native contracts permit them. Portfolio attempts and normalized evidence must belong to the request, candidates must reference a portfolio attempt, and reconstructions must reference the candidate and matching environment lock. Kernel acceptance is retained as descriptive reconstruction evidence and can become authoritative only when the separate kernel stage emits its own receipt.
- Backlog alignment: HSSL-BENCH-015 closes the focused HSSL-G033 gap without a child goal: the existing aggregate goal is already bounded by the adapter output and its focused integration validation. No generated supervisor todo/vector metadata requires manual edits; the discovery receipt records the implementation and validation evidence for reconciliation.

## HSSL-G034 Integrate Leanstral proof synthesis and bounded repair

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G030
- Fib priority: 3
- Track: benchmark-adapters
- Priority: P0
- Bundle: objective/hssl/adapters-leanstral
- Goal: Reuse the local Leanstral provider for strict Lean proof drafts and one bounded failure repair without allowing model output to become authoritative.
- Evidence: HSSLEV0342A4C
- Outputs: benchmarks/logic_pipeline/adapters.py, tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py -q
- Acceptance: Requests carry fixed obligation IDs and bounded context, responses reject forbidden constructs and malformed schemas, model/kernel resource lanes differ, and all drafts remain unverified.
- Gap task: Implement the Leanstral adapter and bounded repair contract over success, rejection, timeout, and unavailable-backend cases.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.adapters.HSSLEV0342A4C` and `LeanstralAdapter` lazily reuse the supervisor-owned local `LeanstralProofProvider`. The adapter binds exactly one fixed obligation ID, bounds the provider payload, records only draft artifacts, rejects schema drift, obligation rebinding, forbidden Lean escape hatches, and model authority claims, and maps timeout, malformed, and unavailable outcomes to explicit stage statuses.
- Bounded repair contract: A request may carry one reviewed failure diagnostic and failed draft with `repair_attempt: 1`; the adapter forwards that context once, records `mode: repair` and `repair_attempts: 1`, and rejects a second attempt before invoking the provider. Model inference stays in the `model` lane while kernel checking is declared separately as `kernel`; no Leanstral record can set `kernel_accepted` or create a kernel receipt.
- Scope boundary: HSSL-G034 establishes the adapter-level transport, validation,
  and one-attempt upper bound for a repair request. It does not assert that
  protocol revision 1 schedules a post-kernel repair, that the frozen revision
  1 corpus contains an independently reviewed repair-trigger case, or that
  repair efficacy has been measured. The unchanged revision 1 ablation graph
  performs one pre-kernel Leanstral synthesis invocation when its frozen route
  calls Leanstral; a separate protocol/corpus revision is required to feed an
  independently kernel-rejected draft back through this transport.
- Backlog alignment: HSSL-BENCH-016 closes the focused HSSL-G034 gap without a child goal. The focused integration suite covers synthesis, one repair, malformed/forbidden responses, timeout, unavailable backend, fixed-obligation and bound checks; generated supervisor todo/vector state remains supervisor-owned.

## HSSL-G035 Bind all claimed successes to kernel and provenance receipts

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G030
- Fib priority: 5
- Track: benchmark-adapters
- Priority: P0
- Bundle: objective/hssl/adapters-receipts
- Goal: Produce a single case-result record that binds every stage digest, route, resource measurement, reconstruction, kernel outcome, and environment identity.
- Evidence: HSSLEV0357C0D
- Outputs: benchmarks/logic_pipeline/contracts.py, benchmarks/logic_pipeline/metrics.py, tests/integration/benchmarks/logic_pipeline/test_kernel_bound_results.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_kernel_bound_results.py -q
- Acceptance: Tampered, mixed-request, stale-environment, model-only, and solver-only records cannot deserialize or aggregate as verified.
- Gap task: Implement content-addressed case results and adversarial provenance validation.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.contracts.HSSLEV0357C0D` binds HSSL-G035 to `CaseResultReceipt` and the strengthened `CaseResultRecord`, while `benchmarks.logic_pipeline.metrics.HSSLEV0357C0D` and `aggregate_case_results` admit verified outcomes only after full receipt validation.
- Receipt contract: A case result embeds its stages and an independently content-addressed receipt over the canonical executed route, every stage/provenance/telemetry digest, the cumulative upstream chain, per-stage resource lane, Hammer reconstruction join when present, terminal kernel outcome and receipt, and pinned environment identity. Verified deserialization requires one input identity, one non-null environment, native-kernel authority, and an accepted terminal kernel record. Aggregation revalidates canonical serialization, environment freshness, same-arm identity, unique cases, and every receipt before a success enters the numerator; content tampering, mixed request/case/manifest/variant/cache records, stale environments, broken reconstruction joins, wrong resource lanes, and model- or solver-only claims fail closed.
- Backlog alignment: HSSL-G035 remains one cohesive bounded child of HSSL-G030. Its existing contracts, metrics, and integration-test outputs plus the focused validation cover the gap, so no smaller child goal, parent edge, output refinement, or manual generated todo/vector edit is required; the goal remains active for supervisor reconciliation.

## HSSL-G040 Freeze and measure the current baseline

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G011, HSSL-G021, HSSL-G022, HSSL-G023, HSSL-G031, HSSL-G032, HSSL-G033, HSSL-G034, HSSL-G035
- Fib priority: 8
- Track: benchmark-baseline
- Priority: P0
- Bundle: objective/hssl/baseline
- Goal: Capture the exact current effective architecture as A0 with fixed configuration, immutable case IDs, cold and warm cache modes, and complete telemetry, including whether spaCy used its requested model or blank fallback.
- Evidence: HSSLEV0404E6E
- Outputs: benchmarks/logic_pipeline/runner.py, workspace/benchmarks/hammer-symai-spacy-leanstral
- Validation: python benchmarks/logic_pipeline/runner.py --variant A0 --split pilot --validate-only
- Acceptance: The baseline is reproducible from pinned commits, records requested and effective configuration, emits one valid case result per eligible pilot case, and does not invoke components outside the current route.
- Gap task: Implement the A0 runner and record the frozen baseline manifest before comparative tuning.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.runner.HSSLEV0404E6E` binds this goal to the strict A0 manifest loader and execution boundary. The canonical manifest at `workspace/benchmarks/hammer-symai-spacy-leanstral/a0-baseline-v1/state/baseline-manifest.json` has SHA-256 `6b37a6493d6328102b558258843218128ad0bf6f8cc7be13f8d0c2e0bb61e156`.
- Frozen baseline contract: A0 pins repository commit `2a1be00b1b76e6652c25d418752affbf0f85d176`, every recorded submodule gitlink, the two production route source digests, protocol and corpus identities, the ordered ten-case pilot membership, the complete `ModalLogicCodecConfig`, and distinct cold/warm `RunContract` cache namespaces. The requested spaCy model is `en_core_web_sm`; the frozen effective observation is spaCy 3.8.14 using `spacy.blank:en` with `sentencizer` and `spacy_used_fallback_model=true`. The only execution entry point is the existing composite `DeterministicModalLogicCodec.encode`; SyMAI, Hammer, and Leanstral are explicitly out of route.
- Measurement contract: Validate-only performs no backend import, directory creation, or write. Normal execution lazily invokes the frozen current entry point once per case and cache mode, emits twenty content-addressed `CaseResultRecord` values with complete per-stage telemetry, preserves infrastructure failures as results, never fabricates kernel verification, writes only below the selected isolated run root, and refuses output overwrite.
- Backlog alignment: HSSL-G040 remains one cohesive baseline-freeze goal. HSSL-G050 already owns the broader multi-variant scheduler, resume, and randomized block order, so no smaller child goal, parent edge, or manual generated todo/vector status edit is needed; supervisor reconciliation remains validation-driven.

## HSSL-G050 Implement the stage-aware ablation runner

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G040
- Fib priority: 13
- Track: benchmark-execution
- Priority: P0
- Bundle: objective/hssl/runner
- Goal: Execute A0 through A12 plus the S1 safety diagnostic with identical case inputs, bounded resources, randomized block order, isolated caches, and resumable immutable records.
- Evidence: HSSLEV0501F2F
- Outputs: benchmarks/logic_pipeline/runner.py, benchmarks/logic_pipeline/variants.py, tests/integration/benchmarks/logic_pipeline/test_runner.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_runner.py -q
- Acceptance: Variant definitions are explicit and stage-aware, requested and effective configuration are both recorded, unavailable capabilities never silently change arms, resume never duplicates a completed case, order and seeds are recorded, and failures cannot disappear from results.
- Gap task: Implement the variant registry, paired scheduler, resume semantics, and validation tests.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.runner.HSSLEV0501F2F` binds HSSL-G050 to the stage-aware ablation execution boundary. `benchmarks.logic_pipeline.variants.VARIANT_REGISTRY` contains exactly one immutable `VariantDefinition` for every frozen A0-A12 and S1 arm, with explicit canonical stage routes, parser/routing/proof-order policies, capability requirements, and requested configuration identities; A6 records Leanstral-first as a proof-order policy while persisted stage records retain the canonical `StageName` order required by `CaseResultRecord`.
- Scheduling and isolation contract: `ResourceLimits`, `ScheduledCase`, `AblationPlan`, and `build_ablation_plan` bind the frozen protocol, corpus and split identities, registry, requested arms, cache modes, resource limits, configuration identities, and operator seed before execution. Each `(case, cache mode)` forms a paired block over identical self-contained immutable input and payload digest; seed-bound SHA-256 ranks record both block and arm order reproducibly. Every task receives a strict `RunContract` and `CacheScope`, isolating run, protocol, variant, split, and cold/warm state; a missing required capability remains an explicit unavailable result for the requested arm and can never select another effective arm.
- Persistence and resume contract: `execute_ablation` canonically validates and writes every success, capability exclusion, stage failure, infrastructure failure, and raised backend exception as one immutable per-job result. Resume reparses the plan and existing result files, skips only an exact completed task identity, and fails closed on duplicate, corrupt, stale, foreign, or conflicting evidence, so completed work is neither rerun nor silently lost. The existing frozen A0 CLI and API remain available.
- Backlog alignment: HSSL-G050 remains one cohesive runner work item. Its registry, scheduler/persistence implementation, focused integration validation, objective-heap contract, and supervisor discovery receipt cover HSSLEV0501F2F without a smaller child goal. Existing children HSSL-G051 through HSSL-G053 continue to own comparative front-end, proof-order, and delegation analyses; generated todo-vector, objective bundle, and task status remain supervisor-owned and are not manually edited.

## HSSL-G051 Measure spaCy and SyMAI front-end overlap

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G050
- Fib priority: 8
- Track: benchmark-execution
- Priority: P1
- Bundle: objective/hssl/front-end-ablation
- Goal: Compare A0, controlled full spaCy, regex/legal parsing, forced blank-model fallback, gated SyMAI, and always-on SyMAI on semantic quality, ambiguity handling, latency, model calls, and regressions.
- Evidence: HSSLEV0519C80
- Outputs: workspace/benchmarks/hammer-symai-spacy-leanstral/results, docs/performance_snapshots
- Validation: python benchmarks/logic_pipeline/report.py --section frontend --validate
- Acceptance: Results are paired by case and stratum, cold and warm caches are separate, disagreements are retained, and each tool's unique wins and unnecessary calls are quantified.
- Gap task: Run and analyze A0, A1, A4, A5, A7, and A8 on pilot and shortlisted development cases.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.report.HSSLEV0519C80` binds HSSL-G051 to the strict spaCy/SyMAI front-end overlap report. The canonical capture at `workspace/benchmarks/hammer-symai-spacy-leanstral/results/frontend-overlap-v1.json` has SHA-256 `86cc7263efe890a80e0ecf3518eaefaad8dfbabb4fb35d544be83905e4c32404` and retains all 240 coordinates formed by the ten reviewed pilot cases, ten reviewed development cases, six frozen arms, and separate cold/warm modes.
- Front-end measurement contract: Validation binds every row to the reviewed case, split, stratum, expected class, frozen arm policy, and cache mode; a measured replay must additionally embed a strict `CaseResultRecord`, match its requested route, front-end semantic payload digest, and latency/model-call telemetry. All aggregates are recomputed from case observations and remain split/cache/stratum aware: normalized-IR exact match, deterministic semantic equivalence, ambiguity and fail-closed classification, latency, model calls, pairwise disagreements, component-unique wins, A0 regressions, and unnecessary SyMAI calls. The A4/A1, A7/A1, and A8/A1 call comparisons are explicitly descriptive because the requested matrix has no unconfounded A3 SyMAI-off arm; only A5/A4 is interpreted as a gate-efficiency control.
- Captured missingness: The 2026-07-24 preflight found the current codec, regex/legal parser, and blank-model control available, the requested full spaCy pipeline unavailable, and SyMAI/router identities degraded. Every scheduled observation is therefore retained as unavailable with null efficacy metrics; no available control is run alone, no blank/regex route substitutes for full spaCy, and zero calls or wins are not presented as efficiency evidence. The development scope uses all reviewed development cases without inspecting outcomes, avoiding an unfrozen, post-outcome case shortlist and leaving holdout untouched.
- Backlog alignment: HSSL-G051 remains one cohesive front-end analysis goal. The report contract already supports both missingness capture and a later measured replay, so capability gaps do not need a smaller code child goal. Generated todo-vector, objective-bundle, and task status remain supervisor-owned and were not edited manually; reconciliation is driven by HSSLEV0519C80 and the required validation command.

## HSSL-G052 Measure Hammer and Leanstral proof overlap and ordering

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G050
- Fib priority: 8
- Track: benchmark-execution
- Priority: P0
- Bundle: objective/hssl/proof-ablation
- Goal: Compare deterministic Hammer, Hammer-first Leanstral fallback, Leanstral-first, no-Hammer, learned-selector, LLM-ranking, and duplicated-work routes using kernel-verified outcomes.
- Evidence: HSSLEV0526A41
- Outputs: workspace/benchmarks/hammer-symai-spacy-leanstral/results, docs/performance_snapshots
- Validation: python benchmarks/logic_pipeline/report.py --section proof --validate
- Acceptance: Solver/model claims never count without kernel acceptance; premise recall, candidate creation, reconstruction, repair, latency, and unique verified wins are reported separately.
- Gap task: Run and analyze A2 through A4 and A6 through A12 on eligible pilot proof cases, and compare S1 legacy SymbolicAI predictions only as non-authoritative safety evidence.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.report.HSSLEV0526A41` binds HSSL-G052 to the strict proof-overlap and ordering report. The canonical capture at `workspace/benchmarks/hammer-symai-spacy-leanstral/results/proof-overlap-ordering-v1.json` has SHA-256 `dae3faa6af66d5a78156dad69fb93151c8f600a1d7f07bada8e7ae6943eef9b9` and covers all 154 coordinates formed by the seven eligible pilot proof cases, ten primary arms plus S1, and separate cold/warm modes.
- Proof measurement contract: Validation derives every aggregate from exact case-level observations, enforces the frozen A2-A4/A6-A12 policies (including Leanstral-first A6/A12 and no-Hammer A9), and reports premise recall, Hammer and Leanstral candidate creation/overlap, reconstruction, repair, native-kernel completion, component-unique wins, latency, model calls, and preregistered pairwise ordering/selector/ranker/duplicated-work comparisons separately. A verified row requires native-kernel authority, acceptance, and a receipt digest; solver/model assertions alone cannot enter the numerator. S1 is serialized in a separate diagnostic and cannot verify or enter primary metrics. Missing gold premise IDs produce a null metric with `gold_premise_set_unavailable`, never a fabricated zero or predicate-recall surrogate.
- Captured missingness: The 2026-07-24 preflight found Hammer/cvc5 and the Lean kernel available, but the requested full spaCy pipeline and Leanstral service unavailable and SyMAI/router identities degraded. The canonical artifact therefore retains every scheduled cell as explicitly unavailable and makes no proof-efficacy conclusion. The same validator is ready to ingest a measured replay once those pinned capabilities and independently reviewed premise sets exist; missing cells, arm substitution, stale ordering, aggregate tampering, or unreceipted verification fail closed.
- Backlog alignment: HSSL-G052 remains one cohesive proof-ablation analysis goal. Capability missingness is durable execution evidence rather than a silently selected substitute, and the complete report contract already owns replay validation, so no smaller code child goal is needed. Generated todo-vector, objective-bundle, and task status remain supervisor-owned and were not edited manually; reconciliation is driven by HSSLEV0526A41 and the required validation command.

## HSSL-G053 Implement and compare conditional delegation policies

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G050
- Fib priority: 13
- Track: benchmark-execution
- Priority: P0
- Bundle: objective/hssl/delegation
- Goal: Compare always-on, deterministic-first, proof-family, and bounded learned routing while preserving identical verification and resource limits.
- Evidence: HSSLEV0533D02
- Outputs: benchmarks/logic_pipeline/delegation.py, tests/unit/benchmarks/logic_pipeline/test_delegation.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_delegation.py -q
- Acceptance: Every route decision is deterministic or provenance-bearing, thresholds are frozen before holdout, recursive and unlimited escalation is impossible, and unnecessary-call rate is measurable.
- Gap task: Implement P0 through P3 and compare routing efficiency on pilot/development cases.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.delegation.HSSLEV0533D02` binds HSSL-G053 to the dependency-free conditional-routing boundary. `DelegationPolicyConfig`, `RoutingSignals`, `DelegationDecision`, and `route_case` implement P0 always-on, P1 deterministic-first, P2 proof-family, and P3 bounded learned routing as immutable, content-addressed plans. Decisions use only pre-outcome routing signals, retain canonical stage order separately from proof invocation order, end at the native kernel, and cannot repeat a component or cross the Hammer/Leanstral boundary more than once.
- Provenance, holdout, and resource contract: P0-P2 decisions are deterministic and reject learned metadata. P3 requires a pinned selector, feature schema, development-only training manifest and seed, per-case feature-vector digest, scores, and inclusive frozen thresholds; holdout routing rejects any thresholds not frozen before access. Every policy retains the exact same validated `ResourceLimits` payload and digest, the same protocol identity, the same native-kernel verification authority, and the same three-component allowlist; a learned score can select a bounded route but cannot alter budgets, verification, or trust.
- Comparison contract: `DelegationObservation` accepts useful-component attribution only when the component was invoked and a native-kernel receipt supports the verified gain. `compare_delegation_policies` requires a complete paired P0-P3 matrix over identical pilot/development case, split, cache, input, protocol, manifest, label, and resource identities. It reports verified outcomes, model/solver/component calls, escalation precision/recall, resolution before SyMAI/Leanstral, and `unnecessary_call_rate = (component calls - kernel-verified useful component calls) / component calls`, defined as zero for a zero-call denominator, without collapsing safety and cost into one score.
- Backlog alignment: HSSL-G053 remains one cohesive bounded child of HSSL-G050. Its policy implementation, focused unit validation, objective-heap contract, and supervisor discovery receipt cover HSSLEV0533D02 without a smaller child goal. Generated todo-vector, objective bundle, and task status remain supervisor-owned and are not manually edited.

## HSSL-G060 Produce reproducible statistics and Pareto analysis

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G051, HSSL-G052, HSSL-G053
- Fib priority: 21
- Track: benchmark-analysis
- Priority: P0
- Bundle: objective/hssl/analysis
- Goal: Evaluate paired quality, safety, latency, resource, routing, and reliability deltas with confidence intervals and case-level traceability.
- Evidence: HSSLEV0608F63
- Outputs: benchmarks/logic_pipeline/statistics.py, benchmarks/logic_pipeline/report.py, tests/unit/benchmarks/logic_pipeline/test_statistics.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_statistics.py -q
- Acceptance: Bootstrap and paired binary analyses are deterministic for a seed, missingness is explicit, strata are preserved, exploratory multiplicity is labeled, and aggregate numbers link to case records.
- Gap task: Implement the statistical pipeline, Pareto frontier, and reproducible report validation.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.statistics.HSSLEV0608F63` binds HSSL-G060 to the dependency-free inferential boundary, and `benchmarks.logic_pipeline.report.HSSLEV0608F63` exposes the same marker through the report entry point. Immutable, canonically serialized statistical plans, comparison specifications, paired observations, requests, analyses, Pareto objectives, and Pareto candidates retain the frozen protocol identity and cover quality, safety, latency, resource, routing, and reliability as separate analysis domains.
- Paired statistical contract: Every observation binds the run, case, corpus manifest, split, cache mode, A0/candidate arm, stratum, and both source-result SHA-256 receipts; each request identifies logic-family, difficulty, ambiguity, proof-route, or joint stratification so those partitions are never silently pooled. Only capability-unavailable, independently established invalid-fixture, and infrastructure-failure pairs become explicit null missingness; logical failures and regressions remain measured. Point results expose candidate-minus-baseline, binary percentage-point, relative, and direction-adjusted deltas. Seeded pair-within-stratum percentile bootstrap intervals use a recorded R-7 quantile convention; continuous metrics support paired mean or paired median effects and retain p50/p95/p99 arm distributions. Binary results retain the complete concordant/discordant case table and exact two-sided McNemar/binomial result. Exploratory families are named and deterministically Holm adjusted, while preregistered primary tests are labeled unadjusted.
- Traceability, Pareto, and report contract: Every overall and stratum aggregate is recomputed from canonical case traces containing both result receipts and the observation digest. Pareto points must link to known analysis digests and exactly the case-result receipts behind those analyses. Dominance honors maximize/minimize directions, ignores report-only dimensions, requires one strict improvement, retains equal trade-off points, makes missing objectives ineligible, and treats safety as a hard feasibility condition rather than a scalar. `report.py --section statistics --validate --results-path <canonical-json>` reloads strict canonical JSON, rejects duplicate keys, recomputes all intervals, multiplicity adjustments, source links, the frontier, and the artifact digest, without changing the existing front-end or proof report schemas.
- Backlog alignment: HSSL-G060 remains one cohesive analysis work item because the statistical plan, paired inference, missingness, traceability, Pareto, and report-validation contracts share one source-evidence boundary and focused suite. HSSL-G061 remains the existing bounded child for marginal delegation value and operational-complexity accounting, so no smaller child goal is needed. Generated todo-vector, objective-bundle, and task-status metadata remain supervisor-owned and are not manually edited.

## HSSL-G061 Quantify delegation value and complexity cost

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G060
- Fib priority: 13
- Track: benchmark-analysis
- Priority: P1
- Bundle: objective/hssl/analysis
- Goal: Measure verified gains per model call, solver process, accelerator-minute, retry, and operational component so overlap is priced rather than hidden.
- Evidence: HSSLEV0615B24
- Outputs: benchmarks/logic_pipeline/metrics.py, benchmarks/logic_pipeline/report.py
- Validation: python benchmarks/logic_pipeline/report.py --section efficiency --validate
- Acceptance: The report exposes marginal and cumulative value for each escalation, unnecessary-call rate, failure burden, and a complexity-adjusted Pareto frontier without collapsing safety into one score.
- Gap task: Add delegation-efficiency and operational-complexity accounting.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.metrics.HSSLEV0615B24` is the stable AST evidence symbol for receipt-bound delegation value and operational-complexity accounting; `benchmarks.logic_pipeline.report.HSSLEV0615B24` exposes the same marker through the report boundary. `EfficiencyEscalation` freezes the contiguous A1 deterministic-core → A2 Hammer → A3 bounded Leanstral fallback → A4 ambiguity-gated SyMAI chain. Every `EfficiencyObservation` embeds and revalidates a complete `CaseResultRecord` and joins it by digest and environment to an independently content-addressed `EfficiencyResourceReceipt`.
- Paired value and resource contract: Analysis requires the same protocol, run, reviewed manifest, case/input identities, split, cold-or-warm cache mode, environment, and complete case set at every escalation. Each edge reports candidate-only kernel-verified wins, baseline-only regressions, concordant cells, explicit missing pairs, gross gain, regression, and net delta; marginal rows compare the immediate parent and cumulative rows compare A1. Model calls and retries must exactly match component stage telemetry. True solver-process and accelerator-minute values come only from the bound operational meter and carry explicit missing reasons rather than being inferred from Hammer presence or model-lane wall time. Each row retains component calls, native-kernel-supported useful calls, failed attempts, and unique deployed components. Gross and net value are independently normalized by model call, solver process, accelerator-minute, retry, and operational component; a zero, nonpositive, missing, or unmeasured denominator yields a null ratio and typed reason.
- Failure, overlap, and report contract: Unnecessary-call accounting reuses the G053 definition `(component calls - kernel-verified useful component calls) / component calls`, with zero defined only for a measured zero-call denominator. Logical nonverification/rejection, capability exclusions, infrastructure failures, stage failures, retries, stable failure-code counts, and failed component attempts remain separate burdens. The complexity frontier maximizes kernel-verified completion while independently minimizing model calls, solver processes, accelerator minutes, retries, operational-component count, unnecessary-call rate, and failed attempts; it uses no weighted complexity or safety score. Any verified invalid control is hard-ineligible, equal points and genuine trade-offs remain, and missing quality or cost evidence cannot enter the frontier. `report.py --section efficiency --validate [--results-path <canonical-json>]` strictly reparses receipts, requires canonical ordering/JSON, recomputes the matrix, all values and denominators, the safety-gated frontier, and the artifact digest. With no run-scoped input, the required command validates an explicit capability-preflight report whose A1-A4 values and ratios remain null rather than manufacturing efficacy.
- Backlog alignment: HSSL-G061 remains one cohesive bounded child of HSSL-G060 because the paired case-result/resource-receipt graph jointly determines escalation value, overlap cost, failure burden, and Pareto eligibility. No smaller child goal or output refinement is needed. Generated todo-vector, objective-bundle, and task-status metadata remain supervisor-owned and are not manually edited; the supervisor can reconcile HSSLEV0615B24 from the AST symbol, objective heap, discovery receipt, and required validator.

## HSSL-G070 Validate robustness, replay, and failure isolation

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G050
- Fib priority: 34
- Track: benchmark-robustness
- Priority: P0
- Bundle: objective/hssl/robustness
- Goal: Prove that results replay in a fresh worktree and remain safe under missing tools, malformed outputs, timeouts, cancellations, cache corruption, and backend drift.
- Evidence: HSSLEV0702E85
- Outputs: tests/integration/benchmarks/logic_pipeline/test_failure_isolation.py, benchmarks/logic_pipeline/report.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_failure_isolation.py -q
- Acceptance: Injected failures are classified, bounded, and local to their case; no orphaned child survives; successful receipts replay against pinned environments; corrupt or stale receipts fail.
- Gap task: Implement failure injection, receipt replay, and fresh-worktree verification.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.report.HSSLEV0702E85` is the stable AST evidence symbol for the complete failure-injection, bounded-isolation, and pinned fresh-worktree receipt-replay boundary. The canonical robustness report requires exactly one classified observation for missing tools, malformed outputs, timeouts, cancellations, cache corruption, and backend drift, plus at least one independently validated replay.
- Failure-isolation contract: Each injected observation binds one content-addressed case result, the expected frozen `FailureCode`, an elapsed-time ceiling, the sole affected case, and every started/reaped child process. Failed stages short-circuit only their own case; later scheduled cases remain eligible. External validation commands run without a shell in a new process group, with bounded retained output and TERM/KILL cleanup of the whole group. Any surviving non-zombie process is classified as `orphaned_child`, which is an immediate protocol stop.
- Replay contract: Source and replay results are strictly reparsed and provenance-validated against one pinned environment. Their `RunContract` records must bind the corresponding result, retain the same frozen configuration, and use different run and cache namespaces; replay begins cold. Stable case, route, adapter, requested/effective backend, input, output, terminal outcome, kernel, and reconstruction identities must agree. A validated detached `WorktreeSafetyReceipt` binds the replay run to the expected source commit with automatic merge forbidden. Corrupt records, stale environments or commits, same-cache reuse, and coherent backend drift fail closed before they can enter a report.
- Backlog alignment: HSSL-G070 remains one cohesive robustness aggregate and needs no additional child goal. HSSL-G071 and HSSL-G072 remain the correctly scoped children for cache/backend-drift measurement and shared resource/process policy. The generated todo vector, objective bundle, and task status remain supervisor-owned; executable evidence, focused validation, and the supervisor discovery receipt allow validation-driven reconciliation of HSSLEV0702E85.

## HSSL-G071 Separate cold-cache, warm-cache, and backend-drift effects

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G070
- Fib priority: 21
- Track: benchmark-robustness
- Priority: P1
- Bundle: objective/hssl/robustness
- Goal: Prevent caches, model changes, solver changes, and thermal ordering from masquerading as architectural improvement.
- Evidence: HSSLEV0717A46
- Outputs: benchmarks/logic_pipeline/runner.py, tests/integration/benchmarks/logic_pipeline/test_cache_isolation.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_cache_isolation.py -q
- Acceptance: Cache namespaces are variant/run/split bound, warm and cold results are separate, environment drift invalidates comparison, and execution order is recorded and balanced.
- Gap task: Add cache isolation, drift checks, and balanced block scheduling.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.runner.HSSLEV0717A46` is the stable AST evidence symbol for the cache-isolation and drift-comparison boundary. `CacheModePair`, `CacheIsolationReport`, and `validate_cache_isolation` require a complete cold/warm matrix before any cache effect is eligible for comparison, and retain the plan digest, pinned environment, unique cache namespaces, exact execution order, counterbalanced position counts, and both immutable result digests.
- Cache and drift contract: Every durable cache-scope receipt binds the protocol, run, variant, split, cold-or-warm mode, plan, frozen requested configuration, pinned environment, run contract, and canonical cache root. Cache roots resolving outside the selected run output fail before an adapter is invoked. Cold and warm records occupy different namespaces and result paths. Comparative validation requires one non-null environment digest, exact requested identities and routes, and equality under a strict cache-insensitive effective-identity projection that may remove only allowlisted operational cache fields such as namespace, key, hit state, prime/setup receipts, and their dependent provenance digests. Provider, model, endpoint/backend revision, solver, implementation, and every unrecognized identity field remain exact, so backend, route, or environment drift cannot be reported as a cache effect. A warm SyMAI measurement must bind a source-bound prime that is an exact run-scoped miss to the subsequent semantically identical measured hit; prime/setup telemetry remains separately receipted and is included in latency, model-call, retry, memory, and resource totals so warm cost is inclusive. Both direct Leanstral generation and the inner SyMAI-to-Leanstral provider request require `cache_prompt=false`; provider prompt-cache state is never a benchmark warm-cache effect. Missing pairs, mixed schedules, namespace collisions, incomplete setup accounting, and drift fail closed.
- Ordering contract: The immutable plan SHA-ranks paired `(case, cache mode)` blocks, derives one seed-bound arm permutation, and rotates it by recorded block ordinal. This counterbalancing preserves identical inputs within every block while ensuring each arm occupies every thermal position equally, or within one observation when block count is not divisible by arm count. Global, block, and within-block ordinals and canonical job IDs make actual execution order replayable and tamper-evident.
- Backlog alignment: HSSL-G071 remains the correctly bounded cache/backend-drift child of HSSL-G070 and needs no smaller child goal. Its implementation is intentionally paired with the shared resource policy in HSSL-G072 because the same recorded order and environment identity determine comparison eligibility. Generated todo-vector, objective-bundle, and task-status metadata remain supervisor-owned and are not manually edited; the supervisor can reconcile HSSLEV0717A46 from the AST symbol, focused validator, objective heap, and discovery receipt.

## HSSL-G072 Prove bounded resource and process behavior

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G070
- Fib priority: 21
- Track: benchmark-robustness
- Priority: P0
- Bundle: objective/hssl/robustness
- Goal: Keep SyMAI and Leanstral model work, Hammer solver children, kernel checks, and validation jobs inside explicit resource lanes and budgets.
- Evidence: HSSLEV0724C07
- Outputs: tests/integration/benchmarks/logic_pipeline/test_resource_bounds.py, benchmarks/logic_pipeline/capabilities.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_resource_bounds.py -q
- Acceptance: Model sharing cannot duplicate the 119B instance, solver groups cancel cleanly, kernel resources remain distinct, queue delay is measured, and configured caps are enforced.
- Gap task: Integrate resource leases and adversarially test timeout, cancellation, and oversubscription limits.
- Refinement depth: 2
- Evidence implementation: `benchmarks.logic_pipeline.capabilities.HSSLEV0724C07` is the stable AST evidence symbol for the bounded resource and process boundary. The strict `ResourcePolicy`, `ResourceLeaseRequest`, `ResourceLeaseReceipt`, `ResourceLease`, and thread-safe `ResourceScheduler` types implement pre-execution arbitration; `AblationRunResult.resource_receipts` exposes the lease sequence, resource class, measured queue delay, held duration, sharing decision, and release/cancellation outcome for each stage actually executed.
- Lease contract: CPU, model, solver, kernel, and validation are independent operational resource classes with explicit worker, memory, model-instance, solver-process, kernel, validation, queue-timeout, and cancellation-grace ceilings. SyMAI and Leanstral request the same pinned `leanstral-119b-shared` identity, allowing concurrent references to one managed instance while a different large-model identity waits boundedly instead of creating a duplicate. Solver capacity cannot be borrowed by kernel work, kernel capacity cannot be treated as model capacity, queued work records monotonic queue delay, cancellation wakes waiters, and double release or foreign policy/scheduler use fails closed.
- Process and enforcement contract: Every ablation stage acquires its assigned lease before backend dispatch and retains the existing post-execution telemetry ceilings as a second validation boundary for memory, wall time, model calls, and solver use. A caller-supplied scheduler may be stricter than the frozen plan but can never expand its worker, memory, or solver ceilings. External solver and validation commands use argument vectors without a shell in a new process group; timeout sends TERM, waits the frozen grace interval, escalates to KILL, captures bounded output, and reaps the group leader and children. Resource queue timeout/cancellation becomes an explicit `resource_lease_cancellation` case result without cancelling unrelated scheduled cases.
- Backlog alignment: HSSL-G072 remains one cohesive shared resource/process-policy child and needs no additional refinement. Together HSSL-G071 and HSSL-G072 close packet `goal_packet/benchmark_robustness/benchmarks/ac3639a861dc`, covering sibling tasks HSSL-BENCH-007 and HSSL-BENCH-009 through the primary HSSL-BENCH-003 implementation. Generated todo-vector, objective-bundle, and task-status metadata remain supervisor-owned; the supervisor can reconcile HSSLEV0724C07 from the AST symbol, focused validator, objective heap, and discovery receipt.

## HSSL-G080 Complete the pilot and freeze the shortlist

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G061, HSSL-G071, HSSL-G072
- Fib priority: 55
- Track: benchmark-gate
- Priority: P0
- Bundle: objective/hssl/pilot-gate
- Goal: Run the preregistered pilot, reject unsafe or dominated variants, select at most four candidates, and freeze prompts, policies, identities, and thresholds before holdout.
- Evidence: HSSLEV0801D68
- Outputs: workspace/benchmarks/hammer-symai-spacy-leanstral/results, docs/performance_snapshots
- Validation: python benchmarks/logic_pipeline/report.py --gate pilot-shortlist
- Acceptance: Every pilot case has an explicit outcome, invalid controls have zero kernel-verified false positives, failures and exclusions are documented, and shortlist selection uses only pilot/development evidence.
- Gap task: Execute the pilot screen, diagnose infrastructure failures, and freeze the shortlist manifest.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.pilot_gate.HSSLEV0801D68`
  is the stable AST evidence symbol for the strict pilot/shortlist phase gate;
  `benchmarks.logic_pipeline.report.HSSLEV0801D68` exposes the same marker
  through the CLI boundary.
  `python benchmarks/logic_pipeline/report.py --gate pilot-shortlist` strictly
  reparses and validates the canonical
  `workspace/benchmarks/hammer-symai-spacy-leanstral/results/pilot-shortlist-v1.json`
  result, content-addressed as
  `5be9bff6e4f0abf9c096e007b3c3230d09eab943d7ccd58f5fd6d7ab31c746fa`,
  against its allowlisted source evidence; the dated
  `docs/performance_snapshots/2026-07-24_pilot_shortlist.json` companion
  publishes that validated receipt for comparison. A
  structurally valid artifact is not automatically a passed efficacy decision:
  the gate reports the decision state and holdout authorization independently.
- Pilot coverage and missingness contract: The result normalizes the complete
  280-coordinate pilot product: A0 through A12 plus the S1 diagnostic, the ten
  frozen pilot cases, and separate cold and warm cache modes. Every coordinate
  has an explicit terminal outcome. Capability-unavailable and
  preregistered-excluded cells remain typed missingness with null measurements;
  they are never omitted, substituted with another arm, or converted to
  success, logical failure, zero cost, or zero efficacy.
- Safety and efficacy finding: The normalized pilot evidence contains zero
  observed invalid-control kernel false positives and no benchmark
  infrastructure failures. Because the available evidence is explicit
  capability/exclusion missingness rather than measured paired outcomes, all
  efficacy and dominance conclusions remain null. Zero observed safety
  incidents under missing evidence is retained as an observation and is not
  promoted into a claim that a candidate passed the frozen safety or quality
  thresholds.
- Shortlist and authorization finding: No nonbaseline arm is eligible for the
  frozen shortlist, so the nonbaseline shortlist is empty. The decision is
  `incomplete`, not passed or failed, and holdout access is unauthorized. A0 is
  retained only as the baseline and S1 only as an ineligible safety diagnostic;
  neither can manufacture a candidate. The validator fails closed if an
  incomplete decision contains a shortlisted arm, claims efficacy, or
  authorizes holdout.
- Pre-holdout freeze: The receipt binds the preregistered protocol, reviewed
  corpus and pilot membership, arm registry, prompts, routing and fallback
  policies, backend/model/solver identities, cache separation, resource
  policy, and frozen decision thresholds before any holdout access. The empty
  shortlist does not relax or rewrite those inputs, and the snapshot records
  that no holdout audit exists and no tuning or production promotion is
  authorized.
- Backlog alignment: HSSL-G080 remains one cohesive phase-gate aggregate. Its
  complete coordinate matrix, explicit missingness, safety and infrastructure
  findings, frozen inputs, shortlist decision, and holdout lock are one
  indivisible validation boundary, so no smaller child goal is needed.
  Generated todo-vector, objective-bundle, and task-status metadata remain
  supervisor-owned and are not manually edited; the supervisor can reconcile
  HSSLEV0801D68 from the AST symbol, canonical result and snapshot, objective
  heap, discovery receipt, and required validator.

## HSSL-G090 Execute the untouched paired holdout evaluation

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G080
- Fib priority: 89
- Track: benchmark-gate
- Priority: P0
- Bundle: objective/hssl/holdout
- Goal: Compare A0 and frozen shortlisted policies on the untouched holdout with identical manifests, balanced ordering, strict budgets, and kernel-bound receipts.
- Evidence: HSSLEV0909F29
- Outputs: workspace/benchmarks/hammer-symai-spacy-leanstral/results, docs/performance_snapshots
- Validation: python benchmarks/logic_pipeline/report.py --gate holdout
- Acceptance: No tuning occurs after holdout access, every result is paired or explicitly capability-ineligible, all successes replay, and safety, quality, latency, resource, and routing metrics are complete.
- Gap task: Run, replay, and seal the holdout evaluation.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.holdout_gate.HSSLEV0909F29`
  is the stable AST evidence symbol for the paired holdout phase boundary;
  `benchmarks.logic_pipeline.report.HSSLEV0909F29` exposes the same marker
  through the required CLI. `python benchmarks/logic_pipeline/report.py
  --gate holdout` strictly reparses and source-revalidates
  `workspace/benchmarks/hammer-symai-spacy-leanstral/results/holdout-evaluation-v1.json`,
  content-addressed as
  `7d064c5fe82c25ad93c01fd13d4350ae2457f93d3bd32b9cf9a9365b1836c2cd`.
  The dated
  `docs/performance_snapshots/2026-07-24_holdout_evaluation.json` companion
  publishes the validated phase result without converting structural validity
  into an efficacy claim.
- Authorization finding: The source-validated HSSL-G080 receipt is
  `incomplete`, its frozen nonbaseline shortlist is empty, and holdout access
  is explicitly unauthorized and unopened. Running A0 alone would both bypass
  that prerequisite and fail to create a paired comparison. The canonical
  HSSL-G090 result is therefore `blocked` and `sealed_unopened`: it records no
  access ID, namespace, result, metric, kernel receipt, replay receipt, tuning,
  or promotion authority. This is a complete and truthful phase-gate outcome,
  not a completed paired evaluation or safety/quality conclusion.
- Untouched holdout contract: The seal binds reviewed corpus identity
  `58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26`,
  frozen holdout split
  `c7b969ed19a1248143740068e2853ca6132ba3d65dfeec4133e37fad55dbab4a`,
  its ten ordered case and source identities, protocol revision 1, A0, the
  exact frozen shortlist, and separate cold/warm modes. It records that the
  gate inspected manifest identities but no semantic targets or outcomes.
  All twelve nonbaseline variants retain explicit pre-holdout ineligibility
  from the pilot receipt instead of being silently dropped or substituted.
- Execution and replay contract: Any future authorized execution must use the
  identical manifest for A0 and each exact shortlisted arm; alternate arm
  order by frozen case/cache parity; enforce the frozen one-worker,
  one-model-instance, one-solver-process, and distinct kernel/model resource
  lanes; accept success only from the independent native kernel; and replay
  every success plus sampled failures in fresh worktrees and namespaces. The
  generic ablation executor now rejects holdout execution before filesystem or
  backend work, preventing a caller-supplied audit label from bypassing the
  authorization and per-contract audit boundary.
- Missing measurement contract: Safety, quality, latency, resource, and
  routing domains are all present in the canonical artifact, each explicitly
  `not_observed` with null values and a reason. Scheduled/observed pair,
  receipt, and replay counts are truly zero because no work was authorized;
  they are never used as zero-cost efficacy, a safety pass, or vacuous metric
  completeness. The gate fails closed if a redigested artifact injects an
  access, result, non-null metric, replay, tuning event, efficacy statement, or
  production authorization.
- Backlog alignment: HSSL-G090 remains one cohesive phase-gate aggregate.
  Authorization, untouched access state, exact pairing/scheduling, resource
  bounds, kernel receipt authority, replay, metrics, and sealing form one
  indivisible trust boundary, so no smaller child goal is needed. Generated
  todo-vector, objective-bundle, and task-status metadata remain
  supervisor-owned and are not manually edited; the supervisor can reconcile
  HSSLEV0909F29 from the AST symbol, canonical result and snapshot, objective
  heap, discovery receipt, and required validator.

## HSSL-G100 Publish the final architecture decision, delegation matrix, and runbook

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G090
- Fib priority: 1597
- Track: benchmark-decision
- Priority: P0
- Bundle: objective/hssl/final-decision
- Goal: Determine whether Hammer, SyMAI, spaCy, and Leanstral improve the current architecture, assign each component only responsibilities justified by paired holdout evidence, and explain how to reproduce the decision safely.
- Evidence: HSSLEV1006B8A
- Outputs: docs/implementation/runbooks, docs/performance_snapshots
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline -q; python benchmarks/logic_pipeline/report.py --validate-final-decision; python benchmarks/logic_pipeline/report.py --validate-runbook
- Acceptance: The decision cites immutable baseline and holdout manifests, counts only kernel-verified proofs, reports quality, resource, and complexity tradeoffs, selects or rejects every delegation policy, and lets a new operator reproduce capability probing, objective ingestion, pilot, shortlist, holdout, replay, and reporting in a clean worktree without automatically promoting production or touching active progress.
- Gap task: After every prerequisite phase gate has a validated receipt, publish the evidence-backed delegation decision and worktree-safe operator runbook.
- Refinement depth: 1
- Evidence implementation: `benchmarks.logic_pipeline.report.HSSLEV1006B8A`
  is the stable AST evidence symbol for the terminal architecture-decision
  boundary. The dated
  `docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision.json`
  records the source-bound decision under schema
  `ipfs-datasets.logic-pipeline-benchmark.final-architecture-decision.v1`;
  `python benchmarks/logic_pipeline/report.py --validate-final-decision`
  strictly reparses it, recomputes its semantic digest, and cross-validates the
  immutable source files and their internal semantic identities. The
  `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md`
  companion is validated by
  `python benchmarks/logic_pipeline/report.py --validate-runbook`. Together
  they implement evidence term `HSSLEV1006B8A`:
  **evidence-bound final architecture decision, delegation matrix, and
  worktree-safe reproduction runbook**.
- Immutable evidence boundary: The decision cites both the canonical digest
  and byte-content digest of the frozen A0 manifest, front-end overlap report,
  proof overlap report, pilot gate, and holdout gate. Its immutable anchors are
  A0 manifest `6b37a6493d6328102b558258843218128ad0bf6f8cc7be13f8d0c2e0bb61e156`,
  reviewed corpus
  `58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26`,
  frozen holdout split
  `c7b969ed19a1248143740068e2853ca6132ba3d65dfeec4133e37fad55dbab4a`,
  pilot decision
  `5be9bff6e4f0abf9c096e007b3c3230d09eab943d7ccd58f5fd6d7ab31c746fa`,
  and sealed holdout decision
  `7d064c5fe82c25ad93c01fd13d4350ae2457f93d3bd32b9cf9a9365b1836c2cd`.
  The source gate was structurally valid but incomplete: its shortlist is
  empty and it did not authorize holdout access. The holdout therefore remains
  `sealed_unopened`, with zero scheduled pairs, zero observed pairs, and zero
  kernel-verified successes. Those counts describe no authorized execution;
  they are not zero-valued efficacy or safety measurements.
- Final architecture decision: Select **gather more evidence** and retain the
  current production architecture unchanged pending eligible paired holdout
  evidence. This is a fail-closed operational disposition, not a finding that
  A0 outperformed the experimental arms. No variant, component, or routing
  policy is selected; no production promotion is authorized. Adding one
  component, adopting a conditional cascade, and adopting the full stack for
  selected strata are rejected for this decision because none has complete
  paired holdout quality, safety, resource, and complexity evidence. Declaring
  the current architecture superior is also rejected because missing
  comparison data cannot establish superiority.
- Component ownership decision: spaCy retains only its existing A0
  responsibility, including the explicitly recorded degraded blank-model
  fallback; no full-model expansion is justified. SyMAI receives no production
  ambiguity-routing or premise-ranking responsibility. Hammer receives no
  production proof-search responsibility. Leanstral receives no production
  proof-fallback or proof-ordering responsibility. These are deferrals for
  absent paired evidence, not claims that a component is ineffective. Any
  future proof benefit counts only when an independent native-kernel receipt
  accepts the reconstructed result; model or solver claims alone remain
  ineligible.
- Delegation matrix:

  | Arm | Preregistered responsibility | Final disposition |
  | --- | --- | --- |
  | A0 | Exact current effective route | Retain unchanged as the reference only; not a newly promoted candidate |
  | A1 | Full-spaCy deterministic core | Evidence-ineligible; no pilot/development efficacy or paired holdout result |
  | A2 | A1 plus deterministic Hammer | Evidence-ineligible; no paired kernel-verified marginal value |
  | A3 | Hammer-first with bounded Leanstral fallback | Evidence-ineligible; cascade quality and cost unmeasured |
  | A4 | A3 plus ambiguity-gated SyMAI | Evidence-ineligible; conditional-stack value unmeasured |
  | A5 | A4 with SyMAI always on | Evidence-ineligible; gate-efficiency tradeoff unmeasured |
  | A6 | Leanstral before Hammer | Evidence-ineligible; proof-order tradeoff unmeasured |
  | A7 | A4 with regex/legal parser | Evidence-ineligible; spaCy marginal value unmeasured |
  | A8 | A4 with forced spaCy blank fallback | Evidence-ineligible; full-model/fallback tradeoff unmeasured |
  | A9 | A4 without Hammer | Evidence-ineligible; Hammer marginal value unmeasured |
  | A10 | A4 with pinned learned Hammer selector | Evidence-ineligible; learned-selector value unmeasured |
  | A11 | A4 with SyMAI/LLM premise ranking | Evidence-ineligible; ranking overlap and cost unmeasured |
  | A12 | Always-on duplicated-work stress arm | Evidence-ineligible; never infer benefit from preflight zero calls |
  | S1 | Legacy SymbolicAI/kernel-truth diagnostic | Diagnostic only and never candidate-eligible |

- Policy decision: Reject P0 always-on, P1 deterministic-first, P2
  proof-family, and P3 bounded-learned routing from the current production
  decision. All remain valid benchmark policies, but none is selected because
  no policy passed the frozen shortlist and paired holdout gates. P3 also
  remains development-frozen and may not learn from holdout. There are no
  evidence-backed thresholds to publish as production settings; the only
  operative threshold is the fail-closed requirement for a complete,
  source-validated paired holdout receipt.
- Tradeoff finding: Quality values—including kernel-verified completion,
  paired delta from A0, semantic equivalence, normalized IR match, and A0
  regressions—are `not_observed`, not zero. Resource values—including latency,
  model calls, solver processes, accelerator-minutes, peak memory, and
  retries—are `not_observed`, not zero-cost. Complexity values—including
  deployed component count, unnecessary-call rate, failed attempts, marginal
  verified gain per resource, and Pareto eligibility—are also `not_observed`.
  The structural implementation can account for each field, but a
  capability-preflight record cannot supply candidate efficacy or operational
  burden. Safety likewise remains unevaluated on holdout; no observed invalid
  control false positive must not be rewritten as a measured zero rate.
- Reproduction and promotion boundary: A new operator follows the validated
  runbook from a clean detached worktree and run-scoped state root through
  capability probing, supervisor objective ingestion, baseline validation,
  pilot/development execution, shortlist gating, authorized paired holdout,
  fresh-worktree replay, and final reporting. The next eligible decision
  requires pinned full spaCy, SyMAI/llm_router, and Leanstral identities; an
  unchanged complete pilot/development matrix; zero kernel-verified invalid
  controls; a frozen nonempty shortlist; explicit holdout authorization;
  balanced A0/candidate cold and warm pairs; kernel receipts; replay; and
  complete quality, resource, routing, and complexity reports. Benchmark
  validation never changes production routing, merges a worktree, or promotes
  a component automatically.
- Backlog alignment: HSSL-G100 remains one cohesive terminal decision goal.
  Its source binding, fail-closed decision, full A0-A12/S1 and P0-P3
  dispositions, component ownership, tradeoff accounting, and reproduction
  runbook are one publication boundary, so no smaller child goal is needed.
  Generated todo-vector, objective-bundle, and task-status metadata remain
  supervisor-owned and are not manually edited; the supervisor can reconcile
  HSSLEV1006B8A from the AST symbol, decision snapshot, validated runbook,
  objective heap, discovery receipt, and required validators.

## HSSL-G110 Restore and pin the requested full spaCy pipeline

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G100
- Fib priority: 2584
- Track: benchmark-remediation
- Priority: P0
- Bundle: objective/hssl/remediation-spacy
- Goal: Provision the requested full spaCy pipeline reproducibly for a fresh benchmark run without changing the frozen protocol, corpus, variants, prompts, policies, thresholds, or selection inputs.
- Evidence: HSSLEV1103A41
- Outputs: benchmarks/logic_pipeline/runtime_env/spacy.lock, scripts/benchmarks/provision_hssl_spacy.py, tests/integration/benchmarks/logic_pipeline/test_spacy_runtime.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_spacy_runtime.py tests/unit/benchmarks/logic_pipeline/test_spacy_adapter.py -q
- Acceptance: The requested `en_core_web_sm` pipeline and spaCy distribution are version- and artifact-pinned, loadable in the detached benchmark environment, recorded as requested equals effective with no fallback, and a bounded non-corpus smoke receipt proves the full pipeline while the original v1 evidence remains immutable.
- Gap task: Repair and pin the full spaCy runtime outside any frozen evaluation run, then record reproducible provisioning and identity validation.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-up 1 and the validated benchmark runbook.
- Evidence implementation:
  `scripts.benchmarks.provision_hssl_spacy.HSSLEV1103A41` is the stable AST
  evidence symbol for the full-model runtime boundary. The closed-schema
  `benchmarks/logic_pipeline/runtime_env/spacy.lock` is semantically
  content-addressed as
  `f45945e4e8a24305b3ade669ed52da2df2b0af63267b9ef28823b9bac442d68d`;
  `scripts/benchmarks/provision_hssl_spacy.py` owns strict lock parsing,
  artifact verification, detached-environment provisioning, isolated probing,
  canonical receipt construction, and receipt revalidation. The focused
  `tests/integration/benchmarks/logic_pipeline/test_spacy_runtime.py` suite
  exercises that boundary together with the existing fail-closed adapter
  suite.
- Pinned runtime contract: The lock selects spaCy `3.8.14` for CPython 3.12
  from exact Linux aarch64 or x86-64 wheels and selects
  `en_core_web_sm==3.8.0` from its exact platform-independent wheel. Every
  wheel carries a credential-free HTTPS URL, byte size, and SHA-256; the
  model metadata file is separately pinned as
  `7456349002fa8cf31111051bd37fdbea67a1b7f7a0a60ce235466f98a6758125`.
  The spaCy wheel SHA-256 values are
  `daeb64b048f12c059997281aed53eb8776d26416dd313cf17ad6f63124b2b564`
  (aarch64) and
  `6d45715a24446f23b98ec3f09409a1d4111983d1d64613250ee38c3270e21853`
  (x86-64); the model wheel SHA-256 is
  `1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85`.
  The `click==8.3.2` import prerequisite exposed by a clean-environment probe
  is also artifact-pinned rather than left to resolver drift. Validation
  requires the exact locked model metadata, language, enabled
  `tok2vec`/`tagger`/`parser`/`attribute_ruler`/`lemmatizer`/`ner` pipeline,
  disabled `senter`, full annotation set, and spaCy/model versions. Requested
  and effective identities must both be `en_core_web_sm`; any version,
  artifact, metadata, component, annotation, identity, blank-model, regex, or
  fallback drift fails closed.
- Smoke and immutability contract: Provisioning accepts only an explicit
  detached virtual-environment destination, rejects active-run markers,
  current-environment mutation, frozen result namespaces, and repository
  evidence/data paths, and verifies downloaded bytes before installation. It
  executes a fixed 47-byte non-corpus sentence with isolated Python and emits
  only its digest, byte count, annotation/count summary, pipeline identity,
  artifact identities, safety flags, and a recomputable receipt digest. A live
  Linux/aarch64 CPython 3.12 detached probe produced receipt
  `1879cbe401d89530458534394a502b8832a3ff769ec9d927ed5059474ce7ae4a`
  with requested equal to effective, fallback false, all six locked
  annotations present, one sentence, nine tokens, and two entities. The
  command never reads a corpus or holdout, changes production routing, or
  writes an evaluation result; the frozen protocol, corpus, variants, prompts,
  policies, thresholds, selection inputs, and all v1 evidence remain
  unchanged.
- Backlog alignment: HSSL-G110 remains one cohesive bounded runtime
  identity/provisioning goal. The lock, provisioner, AST symbol, focused
  integration coverage, and this evidence record cover HSSLEV1103A41 without
  requiring a smaller child goal or output/parent refinement. HSSL-G120
  separately owns the new-run capability reprobe after all runtime repairs.
  Generated todo-vector, objective-bundle, and task-status metadata remain
  supervisor-owned and were not manually edited; the supervisor can reconcile
  this goal from the AST symbol, lock digest, objective heap, discovery
  receipt, and required validator.

## HSSL-G111 Restore and pin SyMAI and llm_router provider/model identities

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G100
- Fib priority: 4181
- Track: benchmark-remediation
- Priority: P0
- Bundle: objective/hssl/remediation-symai-router
- Goal: Provision SymbolicAI/SyMAI through the repository's existing `llm_router` with one explicit provider/model identity and secret-safe configuration, without creating a second router or model manager.
- Evidence: HSSLEV1118B52
- Outputs: benchmarks/logic_pipeline/runtime_env/symai-router.lock, scripts/benchmarks/provision_hssl_symai_router.py, tests/integration/benchmarks/logic_pipeline/test_symai_router_runtime.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_symai_router_runtime.py tests/unit/benchmarks/logic_pipeline/test_symai_adapter.py -q
- Acceptance: SyMAI and `llm_router` are installed and available; requested and effective provider/model identities are complete and identical; credentials are represented only by presence or digest receipts; setup is noninteractive; recursive routing and unrequested fallback remain disabled; and a bounded non-corpus structured smoke call validates the existing-router path.
- Gap task: Repair package/configuration discovery and pin the SyMAI plus `llm_router` identity used by the fresh run.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-up 1 and the validated benchmark runbook.
- Evidence implementation: `scripts.benchmarks.provision_hssl_symai_router.HSSLEV1118B52`
  is the stable AST receipt. The strict
  `benchmarks/logic_pipeline/runtime_env/symai-router.lock` pins the
  `symbolicai` distribution and `symai` import at 1.14.0, its distribution
  metadata digest, the repository-owned `ipfs_datasets_py.llm_router` and
  `IPFSSyMAINeurosymbolicEngine` path, provider `ipfs_accelerate_py`, model
  `Leanstral-119B`, and the corresponding `ipfs:Leanstral-119B` SyMAI config
  value. Unknown lock fields, package/artifact drift, recursive providers, or
  any enabled provider, model, or local fallback fail closed.
- Provisioning and smoke boundary: The provisioner defaults to a read-only
  availability check. Installation and configuration are explicit,
  noninteractive operations; the installer uses the current interpreter and
  exact requirement without a shell, and configuration is written under an
  operator-supplied isolated prefix with the non-secret `ipfs` routing
  sentinel. Runtime receipts retain credential presence and contextual SHA-256
  only. The opt-in smoke operation makes exactly one zero-retry, deadline- and
  byte-bounded structured call on an authored non-corpus sentence through the
  existing router, serializes no raw output, requires requested and effective
  provider/model equality, and records that no model server or model manager
  was started. The SyMAI engine passes `disable_model_retry=True` whenever
  local fallback is disabled, so the router cannot retry with an unrequested
  default model while reporting the pinned request identity.
- Executable validation: The focused integration suite verifies the strict
  lock and artifact probe, aligned SyMAI/router capability environment,
  isolated config import, secret redaction, exact noninteractive install plan,
  one-call structured contract, identity drift and recursive-route rejection,
  model-fallback disablement, canonical create-only receipts, and hermetic CLI
  check. Existing SyMAI adapter tests continue to cover contract parsing,
  retry bounds, cache isolation, and unavailable-package behavior.
- Backlog alignment: HSSL-G111 remains one cohesive runtime identity boundary,
  so no smaller child goal is needed. Generated todo-vector, objective-bundle,
  and task-status metadata remain supervisor-owned and are not manually
  edited. The supervisor can reconcile HSSLEV1118B52 from the AST symbol,
  runtime lock, provisioner, focused tests, objective heap, and discovery
  receipt.

## HSSL-G112 Restore and pin the shared Leanstral endpoint and model identity

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G100
- Fib priority: 6765
- Track: benchmark-remediation
- Priority: P0
- Bundle: objective/hssl/remediation-leanstral
- Goal: Restore the supervisor-owned Leanstral service, model-manager advertisement, and MCP client discovery path; bind one exact endpoint/provider/model identity shared with SyMAI where configured; and produce a bounded health receipt without opening benchmark inputs.
- Evidence: HSSLEV1126C73
- Outputs: benchmarks/logic_pipeline/runtime_env/leanstral.lock, scripts/benchmarks/provision_hssl_leanstral.py, tests/integration/benchmarks/logic_pipeline/test_leanstral_runtime.py, ipfs_accelerate_py/test/api/test_model_manager_mcp_live.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_leanstral_runtime.py tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py ipfs_accelerate_py/test/api/test_model_manager_mcp_live.py -q
- Acceptance: The existing shared endpoint is reachable through bounded health and model-list calls; the model manager and an MCP client report the exact served Leanstral model and intended service identity; endpoint, provider, model, server build, and receipt digest agree without serializing secrets; no duplicate model server is created; P2P transport, when requested by the configured provider, advertises and dials usable policy-approved addresses and the configured custom port rather than silently substituting another provider; and one non-corpus proof draft remains untrusted until independent native-kernel validation.
- Gap task: Repair the existing shared model-service, model-manager, MCP discovery, and configured P2P path, then pin its Leanstral identity for the fresh run.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-up 1, plus the existing model-serving and P2P deployment contract.
- Evidence implementation: `scripts.benchmarks.provision_hssl_leanstral.HSSLEV1126C73` binds the canonical `benchmarks/logic_pipeline/runtime_env/leanstral.lock` identity to the noninteractive attach-and-verify boundary. The focused runtime suite and live model-manager/MCP discovery suite independently exercise that boundary while the existing Leanstral adapter suite preserves the untrusted-draft and native-kernel authority separation.
- Shared-service identity contract: Lock schema `ipfs-accelerate.hssl-leanstral-runtime-lock.v1` pins endpoint `http://127.0.0.1:8080/v1`, logical routing provider `leanstral_local`, model `Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4`, service `leanstral-119b-shared`, and server build `llama.cpp`, plus bounded health/model-list paths, model-manager advertisement, MCP tools, and the optional P2P provider/custom-port policy. Provisioning verifies the supervisor-owned endpoint and never installs, starts, or mutates a model service. Raw HTTP, model-manager, and MCP observations must expose the exact endpoint/model and truthful `llamacpp` transport provider; the canonical lock binds that observation to the distinct logical routing provider and service identity without relabeling transport evidence. Any advertised service/build metadata must match the lock exactly. Enabled P2P evidence must retain the logical provider and configured port and prove policy-approved advertised/dialed addresses before a content-addressed health receipt is accepted.
- Bounded trust contract: Verification performs only bounded health, model-list/discovery, and one explicitly non-corpus proof-draft probe. Secret values and benchmark inputs are excluded from the lock and receipt. A draft can prove service reachability and identity only: it remains untrusted model output and cannot claim proof verification, kernel acceptance, or native-kernel receipt authority.
- Backlog alignment: HSSL-G112 remains one cohesive shared-runtime identity goal. Endpoint reachability, model-manager advertisement, MCP discovery, configured P2P transport, identity agreement, and the bounded untrusted smoke probe all validate the same locked service, so no smaller child goal is needed. Generated todo-vector, objective-bundle, and task-status metadata remain supervisor-owned and are not manually edited; the supervisor can reconcile HSSLEV1126C73 from the executable marker, canonical lock, provisioning validator, focused tests, objective heap, and discovery receipt.

## HSSL-G113 Reconcile source and submodule freshness in a new run namespace

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G100
- Fib priority: 10946
- Track: benchmark-remediation
- Priority: P0
- Bundle: objective/hssl/remediation-source-isolation
- Goal: Establish a fresh detached benchmark source, exact recursive submodule gitlinks, environment inventory, state root, and cache namespaces without rewriting any frozen v1 manifest, result, or decision.
- Evidence: HSSLEV1134D84
- Outputs: benchmarks/logic_pipeline/source_reconciliation.py, tests/integration/benchmarks/logic_pipeline/test_source_reconciliation.py, workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/state/baseline-manifest.json
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_source_reconciliation.py tests/integration/benchmarks/logic_pipeline/test_worktree_isolation.py tests/integration/benchmarks/logic_pipeline/test_baseline_runner.py -q
- Acceptance: A detached worktree records the exact source commit and every recursive gitlink; old and fresh A0 treatment code and normalized pilot outputs are compared before a new source-bound baseline is accepted; the new run uses disjoint state, result, receipt, worktree, process, and cold/warm cache namespaces; any unexplained A0 drift fails closed; and no v1 artifact or active checkout is mutated.
- Gap task: Reconcile the stale A0 source/gitlink identity and create a behavior-equivalent, source-fresh v2 baseline in a separate run namespace.
- Refinement depth: 1
- Follow-up source: The final decision's immutable-evidence and freshness findings and the runbook's evidence-freshness contract.
- Evidence implementation: `benchmarks.logic_pipeline.source_reconciliation.HSSLEV1134D84`
  is the stable AST evidence symbol for the source-fresh baseline boundary.
  `SourceReconciledBaselineManifest`, `capture_recursive_gitlinks`,
  `compare_a0_outputs`, `reconcile_source`, and the strict canonical
  loader/exclusive writer make freshness executable rather than prose-only.
  The canonical
  `workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/state/baseline-manifest.json`
  uses schema
  `ipfs-datasets.logic-pipeline-benchmark.source-reconciled-baseline.v1`
  and semantic digest
  `6c7084db784022d81abc65148fb0d72a8046da881c4d4b448434b9b13af7e469`.
- Source reconciliation contract: The v2 receipt binds detached outer source
  commit `3e053f6edece026fef48c153aa5c4d62a50da3d2`, its twenty sorted
  recursively discovered gitlinks, and secret-safe environment inventory
  digest `141e63efa862766f860673494bad3406b9b8f0fd40dd4c634822e21326734738`
  to run `reassessment-v2`. The historical and fresh A0 route files remain
  byte-identical, and two complete cold/warm pilot executions normalize to
  the same twenty-coordinate digest
  `599e85c5c19c87c370cdf28f8a156ff5af3fc6f6c186028c963c84f659319b22`.
  Acceptance requires complete treatment and normalized-output equivalence;
  missing, extra, rebound, or partial recursive gitlinks, a source/environment
  mismatch, and any unexplained treatment, status, route, identity, or output
  drift fail closed.
- Namespace and immutability contract: `reassessment-v2` owns distinct state,
  result, receipt, detached-worktree, process, cold-cache, and warm-cache
  namespaces outside `a0-baseline-v1`; cold and warm contracts cannot collide.
  The predecessor manifest remains the immutable v1 schema and semantic
  identity
  `6b37a6493d6328102b558258843218128ad0bf6f8cc7be13f8d0c2e0bb61e156`
  at source commit `2a1be00b1b76e6652c25d418752affbf0f85d176`.
  Reconciliation snapshots every named predecessor artifact, observes the
  active checkout before and after detached preparation, initializes
  submodules only from already provisioned exact objects, and creates the v2
  artifact exclusively. It never refreshes v1 in place, fetches during the
  trust boundary, merges, or changes production routing.
- Backlog alignment: HSSL-G113 remains one cohesive bounded work item because
  source identity, recursive gitlinks, environment identity, behavior
  equivalence, namespace separation, and predecessor immutability jointly
  authorize one v2 baseline. No child goal or output refinement is needed.
  Generated todo-vector, objective-bundle, and task-status metadata remain
  supervisor-owned and were not manually edited; the supervisor can reconcile
  HSSLEV1134D84 from the AST symbol, canonical v2 manifest, objective heap,
  discovery receipt, and required integration suite.

## HSSL-G114 Make every frozen arm execute its real bounded stage graph

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G100
- Fib priority: 17711
- Track: benchmark-remediation
- Priority: P0
- Bundle: objective/hssl/remediation-runtime-execution
- Goal: Replace inert/preflight-only adapter assembly with capability-bound spaCy, SyMAI, Hammer, Leanstral, and independent native-kernel handlers, and execute the exact preregistered A0-A12/S1 dataflow without changing any treatment definition.
- Evidence: HSSLEV1142E95
- Outputs: benchmarks/logic_pipeline/runtime.py, benchmarks/logic_pipeline/adapters.py, benchmarks/logic_pipeline/ablation.py, tests/integration/benchmarks/logic_pipeline/test_live_runtime.py, tests/integration/benchmarks/logic_pipeline/test_ablation_dataflow.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_live_runtime.py tests/integration/benchmarks/logic_pipeline/test_ablation_dataflow.py tests/integration/benchmarks/logic_pipeline/test_kernel_bound_results.py tests/integration/benchmarks/logic_pipeline/test_hammer_adapter.py tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py -q
- Acceptance: Available requested stages cannot silently remain inert or substitute a different arm; typed stage outputs and provenance digests flow to downstream requests; ambiguity gates, bounded proof-failure fallbacks, and the registered Hammer/Leanstral proof order are enforced for every A0-A12/S1 branch; duplicate run contracts are eliminated; frozen reviewed obligations are deterministically compiled into runnable native-kernel inputs without changing their semantic targets; all resource owners are bounded and reaped; and only an independent native-kernel receipt can mark a proof verified.
- Gap task: Repair real backend assembly, stage dataflow, policy routing, proof ordering, formal-obligation compilation, and native-kernel authority before measured execution.
- Refinement depth: 1
- Follow-up source: The final decision's zero-call findings and the runbook's adapter, routing, resource, and kernel trust boundaries.
- Evidence implementation: `benchmarks.logic_pipeline.runtime.HSSLEV1142E95` is the stable AST receipt. `runtime.build_live_runtime` now constructs exact per-variant live routes and `ablation.execute_ablation` executes their typed graph; `tests/integration/benchmarks/logic_pipeline/test_live_runtime.py` and `test_ablation_dataflow.py` cover every frozen arm and the live trust boundary.
- Runtime assembly contract: An `available` capability must bind a callable spaCy, SyMAI/router, Hammer, Leanstral, or independent native-kernel adapter before measurement. Degraded or unavailable capabilities remain explicit unavailable results under the requested arm; no inert available handler, alternate backend, or arm substitution is permitted. A0 binds the current deterministic codec, A7/A8 bind their named regex/blank spaCy modes, A10/A11 retain their selector/ranking identities, and S1 requires its distinct legacy diagnostic handler.
- Frozen dataflow contract: The paired root input and input digest remain identical across stages while immutable `StageArtifact` values carry typed upstream payloads, output digests, effective identities, invocation indices, gate decisions, and consumed-artifact digests. Ambiguity-gated SyMAI emits a successful zero-model-call policy record when closed. Proof invocation is Hammer-only for A2, Hammer then bounded Leanstral fallback for A3/A4/A5/A7/A8/A10/A11, Leanstral-only for A9, Leanstral then Hammer for the A6 reverse cascade, and both Leanstral then Hammer for A12. Durable `StageRecord` values retain canonical wire order and a canonical provenance chain without misrepresenting the actual invocation graph.
- Formal-obligation and kernel trust contract: `compile_reviewed_obligation` deterministically binds the reviewed kind, logic, semantic target, obligation digest, theorem identity, and bounded runnable Lean source template without reading expected outcome labels or asserting the target. `NativeKernelRunner` accepts only a bounded candidate rendered into that fixed input, rejects forbidden proof constructs, and issues an independent content-addressed receipt bound to run, case, arm, obligation, candidate, source, command, environment, outputs, and process outcome. Hammer reconstruction and Leanstral/model claims remain descriptive; only a successful terminal native-kernel receipt can verify, and S1 kernel output is always diagnostic/non-authoritative.
- Resource and lifecycle contract: Each invoked graph node acquires its frozen resource lane and exact model identity under the plan ceiling. Native proof processes use the shared managed-process supervisor with wall/CPU/memory limits, shell-free argv, temporary ownership, whole-process-group TERM/KILL cleanup, and an active-owner zero check before acceptance. `AblationPlan.run_contracts` is the single run-contract source, eliminating executor-side duplicate construction.
- Backlog alignment: HSSL-G114 remains one cohesive runtime trust-boundary goal and needs no smaller child goal. The supervisor can reconcile HSSLEV1142E95 from the AST marker, this objective entry, the HSSL-BENCH-035 discovery receipt, and the required 46-test validation. Generated todo-vector, bundle status, and external objective metadata remain supervisor-owned and were not edited manually.

## HSSL-G115 Build measured reports and a data-driven pilot authorization gate

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G100
- Fib priority: 28657
- Track: benchmark-remediation
- Priority: P0
- Bundle: objective/hssl/remediation-measured-gates
- Goal: Replace preflight-only and hard-coded incomplete report builders with receipt-driven front-end, proof, resource, statistics, and pilot-gate builders that can validate complete measured evidence while preserving fail-closed missingness.
- Evidence: HSSLEV1159F06
- Outputs: benchmarks/logic_pipeline/frontend_report.py, benchmarks/logic_pipeline/pilot_gate.py, benchmarks/logic_pipeline/report.py, tests/unit/benchmarks/logic_pipeline/test_measured_reports.py, tests/unit/benchmarks/logic_pipeline/test_pilot_gate.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_measured_reports.py tests/unit/benchmarks/logic_pipeline/test_frontend_report.py tests/unit/benchmarks/logic_pipeline/test_efficiency_report.py tests/unit/benchmarks/logic_pipeline/test_statistics.py tests/unit/benchmarks/logic_pipeline/test_pilot_gate.py -q
- Acceptance: Complete case receipts produce non-null efficacy, latency, resource, routing, and complexity evidence; capability missingness remains typed and cannot become zero cost or efficacy; invalid-control kernel false positives force rejection; the pilot gate passes only a complete source-bound matrix and freezes a nonempty nondominated shortlist of at most four exact arms plus all immutable selection inputs; and the existing incomplete v1 artifact still validates only as historical fail-closed evidence.
- Gap task: Implement measured artifact derivation and generalize the pilot gate so eligible real evidence, rather than a hard-coded outcome, controls holdout authorization.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-ups 2 and 3.
- Evidence implementation: `benchmarks.logic_pipeline.frontend_report.HSSLEV1159F06`, `benchmarks.logic_pipeline.report.HSSLEV1159F06`, and `benchmarks.logic_pipeline.pilot_gate.HSSLEV1159F06` bind this goal to the measured front-end, aggregate reporting, and authorization trust boundaries. Additive `build_frontend_report(...)` and `build_proof_report(...)` entry points canonicalize receipt-bearing observations, derive their aggregates, and invoke the same strict validators used by artifact loading. The measured pilot gate composes those reports with the existing efficiency and statistics evidence instead of accepting self-asserted summary values.
- Measured-report contract: Complete receipt matrices can populate front-end quality and ambiguity outcomes, proof and native-kernel outcomes, latency, routing/model-call behavior, operational resources, failure burden, statistics, and multidimensional complexity/Pareto evidence. Every measured front-end or proof row embeds a complete `CaseResultRecord` and remains joined to report run, case, arm, split, cache-mode, stage route/payload, telemetry, result digest, environment, and native-kernel authority; efficiency rows additionally retain the applicable operational-resource receipt. Capability-preflight or incomplete evidence remains explicitly typed, with affected values null and reasons retained; missing calls, solver processes, accelerator time, or outcomes are never converted to measured zero cost, zero efficacy, or eligibility.
- Pilot-authorization contract: The measured gate takes already validated front-end, proof, efficiency, and statistics reports plus immutable source bindings and freeze inputs. It requires complete pilot/development coordinate coverage, exact frozen arm identities, non-null decision dimensions, and receipt/content digests before an arm is eligible. Any native-kernel-verified invalid-control false positive rejects the gate. Selection is deterministic from source-bound nondominance evidence rather than arbitrary ranking or truncation; only one to four exact eligible arms may form the deeply frozen shortlist that authorizes holdout, and production promotion remains unauthorized.
- Historical compatibility: The zero-argument v1 load/build/validation path remains available for the checked-in 2026-07-24 artifact. That artifact is valid only as historical, frozen-empty, incomplete evidence: its typed missingness cannot pass the measured gate or authorize holdout. This preserves the existing audit chain while allowing later complete receipts, rather than a hard-coded outcome, to determine authorization.
- Backlog alignment: HSSL-G115 remains one cohesive bounded goal because report derivation and authorization consume the same receipt/source graph and fail-closed missingness rules. HSSL-G140 already owns producing the later reassessment shortlist from a complete run, while HSSL-G116 owns enforcement at the holdout execution boundary; adding another child would duplicate those boundaries. Generated todo-vector, objective-bundle, and task-status metadata remain supervisor-owned and are not edited manually; reconciliation is driven by HSSLEV1159F06, the focused validation command, and the discovery receipt.

## HSSL-G116 Implement fail-closed authorized holdout and detached replay orchestration

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G100
- Fib priority: 46368
- Track: benchmark-remediation
- Priority: P0
- Bundle: objective/hssl/remediation-holdout-replay
- Goal: Implement the execution boundary that can run holdout only from a passed source-bound pilot authorization and can replay evidence only in fresh detached worktrees and isolated namespaces.
- Evidence: HSSLEV1167A17
- Outputs: benchmarks/logic_pipeline/holdout_execution.py, benchmarks/logic_pipeline/replay.py, tests/integration/benchmarks/logic_pipeline/test_authorized_holdout_execution.py, tests/integration/benchmarks/logic_pipeline/test_fresh_worktree_replay.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_authorized_holdout_execution.py tests/integration/benchmarks/logic_pipeline/test_fresh_worktree_replay.py -q
- Acceptance: Before any write or backend call the orchestrator verifies a passed nonempty frozen shortlist and per-contract access audit; it schedules A0 and only exact shortlisted arms on identical holdout manifests with counterbalanced cold/warm order and no tuning; replay requires a new detached worktree, source/environment identity, process namespace, and cache namespace; and unauthorized, drifted, same-run, stale-receipt, or post-access configuration-change attempts fail closed.
- Gap task: Add the authorized holdout and replay code paths that the generic ablation executor intentionally does not provide.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-ups 4 and 5.
- Evidence implementation:
  `benchmarks.logic_pipeline.holdout_execution.HSSLEV1167A17` is the stable
  AST evidence symbol for the complete authorized-holdout and detached-replay
  boundary. `PilotAuthorizationReceipt`, `build_authorized_holdout_plan`,
  `build_holdout_access_audits`, `execute_authorized_holdout`,
  `ReplayRequest`, `ReplayReceipt`, `run_detached_replay`, and
  `validate_detached_replay_pair` provide strict content-addressed records and
  orchestration. The focused
  `tests/integration/benchmarks/logic_pipeline/test_authorized_holdout_execution.py`
  and
  `tests/integration/benchmarks/logic_pipeline/test_fresh_worktree_replay.py`
  suites exercise both trust boundaries, including real disposable Git
  worktrees and injected backend-call counters.
- Authorized execution contract: The executor round-trips and authenticates a
  passed, nonempty, frozen pilot authorization bound to an exact pilot-gate
  digest, source commit, environment, protocol, reviewed corpus, holdout split,
  prompts, policy, model identities, thresholds, and A0 plus at most four
  exact shortlisted configurations. It schedules only A0 and that shortlist
  over every frozen holdout case with separate cold/warm modes and
  counterbalanced paired blocks. Every variant/cache `RunContract` receives a
  deterministic unique access-audit identity, and every complete ordered
  `HoldoutAccessAudit` must bind the identical case manifest, configuration,
  cache, freeze, no-tuning, and evaluation purpose. All of these checks,
  including a fresh non-symlink output namespace, finish before the first
  directory, immutable write, or adapter call. Generic ablation execution
  remains forbidden for holdout, resume is forbidden, and source,
  environment, manifest, arm, audit, purpose, cache, or post-access
  configuration drift fails closed.
- Detached replay contract: Replay first authenticates the completed source
  execution and source worktree receipts, then requires a different run ID,
  process namespace, cold cache namespace, and fresh state root under the exact
  source environment and commit. It live-checks the original detached
  worktree, creates a second detached worktree with
  `prepare_isolated_worktree`, rechecks its live HEAD and detached state, and
  invokes a bounded shell-free command in a new process session with isolated
  run/process/cache variables. Evidence must be a bounded regular non-symlink
  file inside the replay run root before a canonical create-only receipt is
  published. `validate_detached_replay_pair` composes that orchestration proof
  with the existing strict semantic, backend, kernel, reconstruction, and
  cold-cache replay validator. Same-run, reused-state, reused-process,
  reused-cache, stale/foreign receipt, attached/wrong-commit worktree,
  environment/configuration/backend/output drift, timeout, failed command, or
  automatic merge attempts are rejected.
- Backlog alignment: HSSL-G116 remains one cohesive pre-execution trust
  boundary and needs no smaller child goal, output refinement, or parent
  change. HSSL-G150 continues to own the real explicitly authorized holdout
  run and HSSL-G160 continues to own its real replay and publication; this
  implementation does not open the holdout or claim efficacy. Generated todo
  vector, objective-bundle, and task-status metadata remain supervisor-owned
  and were not edited manually. The supervisor can reconcile HSSLEV1167A17
  from the AST symbol, two implementation modules, focused tests, objective
  heap, discovery receipt, and required validator.

## HSSL-G120 Re-probe and freeze the repaired runtime capabilities

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G110, HSSL-G111, HSSL-G112, HSSL-G113, HSSL-G114
- Fib priority: 75025
- Track: benchmark-reassessment
- Priority: P0
- Bundle: objective/hssl/capability-reprobe
- Goal: Start a fresh run ID in a new detached worktree and freeze a capability/environment inventory only after every requested benchmark backend and the independent kernel path passes live identity and bounded smoke validation.
- Evidence: HSSLEV1207F16
- Outputs: docs/performance_snapshots/2026-07-24_hssl_reassessment_capability_inventory.json, workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/receipts
- Validation: python -m benchmarks.logic_pipeline.runtime probe --require spacy_pipeline,symai,llm_router,hammer,leanstral_service,lean_toolchain
- Acceptance: Full spaCy, SyMAI, `llm_router`, Hammer, Leanstral, Lean/Lake, cache, scheduler, and native-kernel records are terminal and identity-pinned; requested equals effective for required components; live imports and bounded health/model/smoke results, not self-asserted environment flags, bind the receipt digests; no holdout data is opened; source/gitlink/worktree/environment identities are frozen; and any unavailable, degraded, drifted, mismatched, fallback, or secret-bearing record closes the run instead of permitting matrix execution.
- Gap task: Run the repaired preflight in a fresh namespace, resolve any remaining mismatch outside the run, and freeze the first fully eligible inventory.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-ups 1 and 2.
- Evidence implementation: `benchmarks.logic_pipeline.runtime.HSSLEV1207F16`
  and `benchmarks.logic_pipeline.capability_reprobe.HSSLEV1207F16` are the
  stable AST receipts for the repaired live-preflight boundary. The canonical
  `reassessment-v2/receipts/capability-inventory.json` inventory is
  content-addressed as
  `9a3d1c61f9d09ebedee0ff446fb9aa72808a467ff1ea41feb8ca204eacb9948b`;
  the cross-file freeze is
  `2446b48d1550fd5792ac9b126dd9fa2785d251f01c1ddc7afcae019889336252`.
  The dated
  `docs/performance_snapshots/2026-07-24_hssl_reassessment_capability_inventory.json`
  publishes the eligible inventory without weakening its receipt validation.
- Detached source and environment contract: The freeze revalidates the
  source-reconciled `reassessment-v2` baseline before probing. It binds
  detached source commit `3e053f6edece026fef48c153aa5c4d62a50da3d2`,
  worktree receipt
  `800cae053102c79c27ed530cd1cb8dd516a3627166e59aba13beb495c65bd974`,
  all twenty recursive gitlinks under identity
  `72f2e124dcd3c03f671cfd8641881b73272800ae0587472b6bbf6192696e4531`,
  CPython/platform/machine identity, run-scoped cache and process state, and
  an explicit no-corpus/no-holdout observation. Source, worktree, gitlink,
  environment, or run-id drift makes the freeze ineligible.
- Live identity and smoke contract: The required command imports and executes
  the locked full `en_core_web_sm` pipeline and all required annotations;
  imports SymbolicAI 1.14.0, the repository `llm_router`, and its existing
  router engine before one zero-retry bounded call to the single served
  Leanstral identity; probes Leanstral health and exact model advertisement;
  imports Hammer and executes a fixed cvc5 satisfiability smoke; and verifies
  Lean and Lake identities. Cache readiness is proven by exclusive create and
  read-after-write, while `ResourceScheduler` is proven by a released kernel
  lease and a bounded reaped process. Each requested identity exactly equals
  its effective identity and each inventory row is joined to a strict,
  content-addressed component receipt.
- Independent kernel and freeze contract: A separate native-kernel receipt,
  `9c341ffbf7eefb6c517b43a028f5a5183813867ce471576b1f134527665ff92d`,
  compiles a fixed non-corpus Lean identity theorem with the pinned native
  executable under a ten-second/output bound and records acceptance,
  timeout state, and process-group reaping. Canonical freeze validation
  rejects unknown/duplicate/noncanonical JSON, missing or symlinked receipt
  files, byte or semantic digest drift, unavailable or degraded rows,
  requested/effective mismatch, fallback, and secret-bearing fields. Evidence
  is create-only and cannot be silently replaced; it authorizes only the
  unchanged reassessment matrix and never changes production routing.
- Backlog alignment: HSSL-G120 remains one cohesive pre-matrix authorization
  boundary. Live component identity, detached-source provenance, native-kernel
  authority, no-holdout safety, and the aggregate freeze cannot be split
  without weakening the eligibility decision, so no child goal is required.
  Generated todo-vector, objective-bundle, and task-status metadata remain
  supervisor-owned and were not manually edited; the supervisor can reconcile
  HSSLEV1207F16 from the AST markers, canonical receipts and snapshot,
  objective heap, discovery receipt, and required validator.

## HSSL-G130 Re-run the unchanged pilot and development matrices

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G120
- Fib priority: 121393
- Track: benchmark-reassessment
- Priority: P0
- Bundle: objective/hssl/matrix-reassessment
- Goal: Execute the unchanged A0-A12 and S1 pilot and development matrices in balanced cold/warm order using the frozen repaired environment and complete case-level evidence.
- Evidence: HSSLEV1305A27
- Outputs: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results, docs/performance_snapshots/2026-07-24_hssl_reassessment_matrix.json
- Validation: python -m benchmarks.logic_pipeline.runtime execute --splits pilot,development --cache-mode both --validate-complete
- Acceptance: All 560 case/arm/cache coordinates are retained as measured or contractually typed terminal outcomes; every invoked stage has a case result, requested/effective identity, telemetry, resource lease, route, and independent native-kernel receipts; invalid controls have zero kernel-verified false positives; failures remain visible; capability missingness is not synthesized as efficacy; cold/warm execution order is counterbalanced; and no frozen protocol, corpus, variant, prompt, policy, threshold, or selection input changes.
- Gap task: Execute and validate a fresh complete pilot/development run without reading or opening holdout semantics.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-up 2.
- Evidence implementation:
  `benchmarks.logic_pipeline.matrix_reassessment.HSSLEV1305A27` is the stable
  matrix-execution evidence symbol and
  `benchmarks.logic_pipeline.runtime.HSSLEV1305A27` exposes the same boundary
  through the supported CLI. The canonical aggregate at
  `workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/matrix-execution-v2.json`
  is complete with semantic SHA-256
  `437961214b97fadd495f65d4a006406b27086e6aeb9f46d8cd27e36df1ed39bb`;
  its public summary is
  `docs/performance_snapshots/2026-07-24_hssl_reassessment_matrix.json`.
- Frozen matrix contract: The executor revalidates the detached source and
  repaired capability freeze before loading exactly the first ten pilot and
  first ten development cases from the reviewed corpus. It schedules the
  unchanged A0-A12 and S1 registry over both cold and warm modes in
  seed-bound, counterbalanced blocks: `2 splits * 10 cases * 14 arms * 2
  cache modes = 560` unique coordinates. The aggregate binds protocol
  `a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3`,
  registry
  `53a106ddd6c68af445d0a3a912b0d7d09e04c6b23500d4c6362bb5c089f2e44f`,
  corpus
  `58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26`,
  repaired environment
  `9a3d1c61f9d09ebedee0ff446fb9aa72808a467ff1ea41feb8ca204eacb9948b`,
  and the exact prior frozen selection receipt by byte and semantic digest.
  Prompts, policies, thresholds, model identities, resources, variants, and
  case inputs remain frozen and tuning is false on every run contract.
- Measured terminal evidence: All 560 case records, 56 run contracts, 56
  isolated cache-scope receipts, two ablation plans, and two resource ledgers
  are retained below the result root. The run records 1,580 invoked stages and
  exactly 1,580 released resource leases. Each split has 66 `not_verified`,
  194 `rejected`, and 20 `unavailable` coordinates; typed capability,
  Leanstral, and SyMAI failures remain visible rather than becoming positive
  efficacy. Ninety-six native-kernel invocations are retained with zero
  acceptances. The 56 invalid-control coordinates therefore have zero
  kernel-verified false positives. S1 capability missingness remains
  nonauthoritative, no fallback or production-route change occurred, and
  neither holdout cases nor holdout semantics were accessed.
- Revision 1 repair scope: HSSL-G130 runs the unchanged frozen revision 1
  graph, which provides one pre-kernel proof-synthesis opportunity per
  scheduled Leanstral stage and no post-kernel feedback edge. Although the
  HSSL-G034 adapter accepts a separately constructed first repair request, the
  revision 1 matrix cannot create that request from a kernel failure. Its
  repair-attempt count is therefore structurally zero, not evidence that
  repair is ineffective or effective.
- Immutable 2026-07-25 diagnostic run: The later run
  `hssl-matrix-20260725T040701Z-21c385c72`, rooted outside the repository at
  `~/.local/share/ipfs_accelerate_py/benchmarks/hssl-repaired-runs/`, is a
  completed, source-bound diagnostic at commit
  `21c385c72f699f2f6963af489cdd49176204f569`. Its strictly validated matrix
  `artifact_sha256` is
  `6e02f487c85285ff1bff56a593a270c2d90fbf5b50ae38cb37da26f2c071ac57`.
  It retained all 560 coordinates, 1,826 invoked stages and released leases,
  348 independent native-kernel invocations, 216 accepted kernel receipts,
  all 56 invalid controls with zero kernel-accepted false positives, and no
  holdout or production-routing activity. Pilot terminal statuses were 113
  verified, 140 not verified, 7 rejected, and 20 unavailable; development
  statuses were 91 verified, 164 not verified, 5 rejected, and 20
  unavailable. The 40 unavailable cells are the frozen S1 typed-unavailable
  diagnostic and the 12 rejected cells report combined Leanstral failures.
  This run is immutable diagnostic evidence: do not modify, resume, delete,
  reuse its namespace, publish it over the canonical v2 matrix, or treat it as
  HSSL-G140 authorization.
- Diagnostic findings and required rerun boundary: Raw terminal receipts
  exposed 216 kernel acceptances while only 204 top-level results were marked
  verified; all 12 rejected top-level results contained an accepted terminal
  kernel receipt, showing that recoverable upstream proof-attempt failure was
  incorrectly given precedence. A9 invoked Leanstral on 18 compiler-native
  successes (10 pilot and 8 development) because the index-zero
  deterministic-first gate was not applied. The 12 combined Leanstral
  failures exposed implicit provider prompt-cache state and operational cache
  metadata in the semantic projection. Warm SyMAI stages recorded zero cache
  hits because no source-bound prime occurred, so cold/warm cost was not an
  honest cache comparison. S1 used the intentional
  `legacy_symbolicai_identity_not_in_repaired_freeze` path for all 40 cells
  rather than a real legacy bridge. Every persisted Leanstral record retained
  `repair_attempts: 0`. The subsequently integrated strict cache-isolation
  gate also rejects the immutable run: it finds six pilot and four development
  cold/warm effective-route disagreements. Eight are Leanstral
  success-versus-typed-provider-failure pairs whose failure side omits the
  resolved provider/model identity; two A6 disagreements include conditional
  Hammer fallback after a warm Leanstral failure, with each A6 coordinate
  contributing both a Leanstral and Hammer disagreement. The requested arm
  identities and registered stage sequences did not drift, but these paired
  paths are not eligible for cache-effect attribution. The index bytes remain
  SHA-256
  `24f2b86469e8a24ffc74b37ec231c2d3f34856a9396277804076a5bd7ea840fc`
  and the public-snapshot bytes remain SHA-256
  `03e80dfc48e3822433c7c22665ca19bfd1db0e1da9cedcf0176a2142111108ae`.
  These are code/protocol findings, not candidate efficacy results; fixes
  require a new clean run ID, capability freeze, unchanged
  pilot/development rerun, and another HSSL-G140 gate while holdout remains
  sealed.
- Validation and recovery contract: The exact required command,
  `python -m benchmarks.logic_pipeline.runtime execute --splits
  pilot,development --cache-mode both --validate-complete`, validates every
  canonical result, run contract, cache scope, plan, lease, source binding,
  selection digest, terminal outcome, and aggregate checksum. Complete
  split-level state can republish a missing aggregate without backend calls;
  partial, drifted, noncanonical, out-of-root, or incomplete state fails
  closed.
- Backlog alignment: HSSL-G130 remains one cohesive execution goal. The two
  split ledgers and their aggregate share one frozen selection, environment,
  safety, and completeness decision, so no smaller child goal is needed.
  Generated todo-vector, objective-bundle, external todo, and task-status
  metadata remain supervisor-owned and were not manually edited. The
  supervisor can reconcile HSSLEV1305A27 from the AST symbols, canonical
  matrix and snapshot, objective heap, discovery receipt, and exact validator.

## HSSL-G140 Validate the complete pilot gate and freeze a nonempty shortlist

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G115, HSSL-G130
- Fib priority: 196418
- Track: benchmark-reassessment
- Priority: P0
- Bundle: objective/hssl/pilot-regate
- Goal: Recompute front-end, proof, efficiency, statistics, safety, and Pareto evidence from source receipts and authorize holdout only for an exact nonempty shortlist of at most four eligible candidates.
- Evidence: HSSLEV1409B38
- Outputs: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/pilot-shortlist-v2.json, docs/performance_snapshots/2026-07-24_hssl_reassessment_pilot_shortlist.json
- Validation: python benchmarks/logic_pipeline/report.py --gate pilot-shortlist --artifact workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/pilot-shortlist-v2.json
- Acceptance: The gate source-validates the complete unchanged matrix, records zero kernel-verified invalid-control false positives, has non-null efficacy and cost evidence, freezes prompts, policies, backend identities, thresholds, resources, and one to four nondominated eligible arms before setting exact holdout authorization; if no arm passes, it keeps holdout sealed and records remediation instead of inventing a shortlist.
- Gap task: Produce and validate the measured pilot/development reports and one source-bound shortlist authorization decision.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-up 3.
- Evidence implementation:
  `benchmarks.logic_pipeline.pilot_reassessment.HSSLEV1409B38` is the stable
  AST-verifiable gate receipt. The reassessment-specific builder, strict
  loader, source recomputation validator, canonical writer, public summary,
  and `report.py --artifact` schema dispatch preserve the historical v1 gate
  while making the persisted v2 decision independently reproducible.
- Source and report contract: The gate first invokes the HSSL-G130 matrix
  validator, then reparses and receipt-validates all 560 exact
  pilot/development case/arm/cache coordinates. It binds matrix byte SHA-256
  `ad76be697eb084517354a9d2b82bf48378f33d820b6f6014a13d5a08bb105ac9`
  and semantic SHA-256
  `437961214b97fadd495f65d4a006406b27086e6aeb9f46d8cd27e36df1ed39bb`.
  Front-end invocation/model-call evidence, proof efficacy, per-coordinate
  latency and operational cost, 40 source-bound A0 pairs per candidate,
  materiality decisions, invalid-control safety, and multidimensional Pareto
  inputs are all recomputed from the validated case records. The 520
  non-missing efficacy observations measure a kernel-verified rate of `0.0`;
  this non-null zero is not treated as a positive result. The missing
  independently reviewed semantic-quality dimension remains explicitly null
  and never becomes zero quality or eligibility.
- Safety, Pareto, and authorization decision: All 56 invalid-control
  coordinates have zero kernel-verified false positives. Every A1-A12 arm has
  non-null receipt-bound cost and paired proof statistics, but none has a
  kernel acceptance or an independent semantic-quality receipt. The gate
  therefore records the observed nondominance calculation while marking every
  candidate ineligible, freezes an exact empty shortlist, keeps holdout sealed,
  and publishes four ordered remediation actions. It does not rank, truncate,
  inspect holdout outcomes, authorize production promotion, or invent the
  nonempty shortlist anticipated by the goal title. A later nonempty decision
  is possible only after repaired evidence passes the unchanged frozen gates.
- Deep-freeze and publication contract: Protocol and registry identities,
  prompts, policies, repaired model/backend identities, isolated cache policy,
  resource policy, thresholds, detached source/gitlinks, tuning prohibition,
  source receipt set, and selected configuration set are individually
  content-addressed into freeze SHA-256
  `9272f193cde2c64496ed780c52c282fe88203ebffeea0b5a3c4b5f3b5897ebb9`.
  The canonical decision has semantic SHA-256
  `2d146c1cb75eb8c2261a3e1be68ba98bf8b2a4996a1839fb36e26f9bd7f37acb`
  and byte SHA-256
  `21713e069e063db32763f563f0184a7d7123a5e559527d54618fadc98d286a48`;
  the dated performance snapshot binds both identities and the sealed
  remediation state.
- Backlog alignment: HSSL-G140 remains one cohesive source-bound phase gate.
  Report derivation, safety, materiality/Pareto selection, deep freeze, and
  authorization share the same validated matrix graph, so splitting them
  would weaken the trust boundary and no child goal or heap refinement is
  needed. Generated todo-vector, objective-bundle, external todo, and task
  status metadata remain supervisor-owned and were not manually edited. The
  supervisor can reconcile HSSLEV1409B38 from the AST marker, canonical
  artifact and snapshot, focused integration tests, this objective entry,
  discovery receipt, and exact validator.

## HSSL-G150 Execute the explicitly authorized paired holdout

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G116, HSSL-G140
- Fib priority: 317811
- Track: benchmark-reassessment
- Priority: P0
- Bundle: objective/hssl/authorized-holdout
- Goal: Open holdout only from the exact passed HSSL-G140 authorization and compare A0 with every exact shortlisted arm on the identical frozen holdout manifest in balanced cold and warm pairs.
- Evidence: HSSLEV1507C49
- Outputs: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/holdout-evaluation-v2.json, docs/performance_snapshots/2026-07-24_hssl_reassessment_holdout.json
- Validation: python benchmarks/logic_pipeline/report.py --gate holdout --artifact workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/holdout-evaluation-v2.json
- Acceptance: A source-bound access audit precedes all holdout activity; A0 and each exact shortlisted arm use identical case/source manifests, frozen identities and limits, isolated cold/warm caches, and counterbalanced ordering; every success requires native-kernel acceptance; every scheduled pair is observed or explicitly failed; no tuning or substitution occurs; and an unauthorized or invalid pilot gate performs zero holdout writes or calls.
- Gap task: Execute, seal, and validate the untouched paired holdout only if the new pilot receipt authorizes it.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-up 4.
- Evidence implementation:
  `benchmarks.logic_pipeline.holdout_reassessment.HSSLEV1507C49` is the
  stable AST-verifiable HSSL-G150 receipt.
  `build_holdout_reassessment_report(...)`,
  `validate_holdout_reassessment_report(...)`, the strict canonical loader,
  atomic artifact/snapshot publisher, and `report.py` holdout schema dispatch
  make the exact v2 phase result independently reproducible while preserving
  the historical v1 gate. Focused integration coverage verifies source
  recomputation, the pre-activity authorization audit, frozen future pairing
  contract, null metrics, artifact/snapshot cross-digests, tamper rejection,
  and the exact objective CLI.
- Prerequisite finding: The exact source-revalidated HSSL-G140 decision has
  semantic SHA-256
  `2d146c1cb75eb8c2261a3e1be68ba98bf8b2a4996a1839fb36e26f9bd7f37acb`,
  byte SHA-256
  `21713e069e063db32763f563f0184a7d7123a5e559527d54618fadc98d286a48`,
  and freeze SHA-256
  `9272f193cde2c64496ed780c52c282fe88203ebffeea0b5a3c4b5f3b5897ebb9`.
  It is `incomplete`, freezes `selected_variant_ids: []`, explicitly records
  `holdout_authorized: false`, and retains an uninspected sealed holdout.
  HSSL-G150 therefore must not execute A0 alone or manufacture an
  authorization; the correct evidence-backed phase result is blocked and
  sealed unopened.
- Zero-activity and future execution contract: The source-first authorization
  audit rejects before reviewed holdout inputs, semantic targets, execution
  namespaces, per-contract access audits, filesystem execution writes, cache
  namespaces, or backend calls are opened. The canonical result records zero
  scheduled, observed, terminal, or failed pairs and retains every efficacy
  and cost domain as explicitly unobserved null rather than synthetic zero.
  It nevertheless freezes the complete authorized path: A0 and every exact
  one-to-four-arm shortlist over the identical ten-case/source manifest;
  separate isolated cold/warm caches; case/cache parity counterbalancing; one
  source-bound audit per run contract before activity; exact protocol,
  registry, source, prompt, policy, model, resource, threshold, and
  configuration identities; native-kernel-only success; terminal accounting
  for every pair; and no fallback, substitution, resume, tuning, or production
  promotion.
- Publication result: The canonical
  `holdout-evaluation-v2.json` has semantic SHA-256
  `e408d7364209dde32ff4f987ba2845306ab226c2f442c0a3d4abfb18521ee44d`
  and byte SHA-256
  `9e712b9ed1fb67c80115d12e3bc92850f23da601543fa59a4cbd700a54b0df9d`.
  The dated public snapshot binds both identities and has byte SHA-256
  `ff8315e79ed69d96cbf1926ea5c1f23e08507b93a5d826270c1161a4d8d4f4a5`.
- Backlog alignment: HSSL-G150 remains one cohesive authorization and
  execution aggregate. Source authorization, the no-side-effect rejection
  boundary, access audits, exact pairing, terminal results, and metrics must
  share one trust graph, so no smaller child goal or heap refinement is
  needed. Generated todo-vector, objective-bundle, external todo, task-status,
  and supervisor backlog metadata remain supervisor-owned and were not
  manually edited. Reconciliation is driven by HSSLEV1507C49, the canonical
  artifact and snapshot, this objective entry, the HSSL-BENCH-041 discovery
  receipt, and the exact validator.

## HSSL-G160 Replay holdout evidence and publish complete reassessment reports

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G150
- Fib priority: 514229
- Track: benchmark-reassessment
- Priority: P0
- Bundle: objective/hssl/replay-report
- Goal: Replay every kernel-verified holdout success and the frozen sample of failures in fresh detached worktrees and isolated namespaces, then recompute all decision domains from source evidence.
- Evidence: HSSLEV1605D50
- Outputs: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/replay, workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/statistics.json, docs/performance_snapshots/2026-07-24_hssl_reassessment_reports.json
- Validation: python benchmarks/logic_pipeline/report.py --section statistics --validate --results-path workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/statistics.json
- Acceptance: Every success and required sampled failure has a fresh-worktree, fresh-cold-cache replay bound to the same source, environment, case, route, and kernel identities; drift, stale receipts, and same-run replay fail; safety, quality, latency, resources, reliability, routing, marginal escalation value, unnecessary calls, and complexity/Pareto reports are complete and non-null where applicable; and all claims trace to case-level and independent native-kernel receipts.
- Gap task: Complete independent replay and validate every report needed for
  a defensible architecture decision. In particular, implement a source-bound
  nonempty replay orchestrator/ingestion path that executes every selected
  success and sampled failure through `run_detached_replay`, validates each
  receipt, and publishes completed replay counts; also implement typed
  attachments for independently measured quality, latency, resource, safety,
  and routing domains instead of hard-coded incomplete placeholders.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-up 5.
- Evidence implementation:
  `benchmarks.logic_pipeline.reassessment_reports.HSSLEV1605D50` is the
  stable AST evidence symbol for source-bound replay selection and complete
  reassessment publication; `benchmarks.logic_pipeline.report.HSSLEV1605D50`
  exposes the same statement at the validator boundary. The dedicated
  builder, source-recomputing validators, strict canonical loaders, atomic
  publisher, and focused integration suite bind the G150 holdout result, G140
  pilot decision, complete reassessment matrix, replay index, paired
  statistics, and public report into one fail-closed graph.
- Exact prerequisite result: The canonical HSSL-G150 artifact was
  revalidated with semantic SHA-256
  `e408d7364209dde32ff4f987ba2845306ab226c2f442c0a3d4abfb18521ee44d`
  and byte SHA-256
  `9e712b9ed1fb67c80115d12e3bc92850f23da601543fa59a4cbd700a54b0df9d`.
  It is structurally valid but blocked and `sealed_unopened`: HSSL-G140 froze
  an empty shortlist and did not authorize holdout access, so it contains
  zero scheduled or observed pairs, successes, failures, and case results,
  with zero execution writes and backend calls. G160 therefore cannot create
  a detached worktree, choose a failure sample, replay A0 alone, or claim
  measured holdout efficacy.
- Replay selection and freshness contract: The tracked canonical
  `reassessment-v2/replay/replay-index.json` records empty success, observed
  failure, and sampled-failure populations; zero required and completed
  replays; no worktree, process, cache, receipt, write, or backend activity;
  `all_observed_successes_replayed=true` only as zero-population accounting;
  and `replay_claimed=false`. It freezes the future nonempty path: distinct
  replay run and process identities, a fresh detached worktree and cold cache,
  identical source/environment/case/variant/route/adapter/native-kernel
  identities, unchanged terminal outcomes, and rejection of stale receipts,
  same-run reuse, configuration drift, and automatic merge.
- Remaining nonempty-path blocker: The zero-population artifact is valid, but
  the current builder is not yet an executable implementation of a future
  nonempty G160 run. It always emits zero completed replays and
  `replay_claimed=false`, and the report builder has no typed attachment API
  for the required independent quality, latency, resource, safety, and routing
  receipts. A later authorized holdout must not advance to G170 until those
  APIs execute, ingest, source-bind, and revalidate real receipts. Empty
  accounting is not evidence that this implementation work is complete.
- Recomputed reports: The canonical `statistics.json` contains forty-eight
  A0-versus-A1-through-A12 comparisons separated by pilot/development split
  and cold/warm cache, totaling 480 case-receipt pairs. Its seeded stratified
  inference and safety-ineligible Pareto result are recomputed by the existing
  strict statistics schema. The dated report enumerates safety, quality,
  latency, resources, reliability, routing, marginal escalation value,
  unnecessary calls, and complexity/Pareto. Available pilot/development
  values remain source-bound; every holdout-only value is explicitly
  `not_applicable_before_authorization` and null, never synthetic zero. The
  report is structurally complete while publishing no holdout efficacy or
  replay claim, and every measured comparison links case-result digests under
  the independent native-kernel-only success rule.
- Publication result: The replay index has semantic SHA-256
  `6248b875566afb7e9706c4f39d28e3a2eea680bd04dfd11f5fee6a5883af27d2`
  and byte SHA-256
  `3fc20f5526b1ed9fe81eed52e3cd0bd17084b0a46361c37e25b6bc7236401649`.
  The statistics report has semantic SHA-256
  `857bae66f9b336de82c6506b469b864f6bcfb1862a67142ba858695e85781b3d`
  and byte SHA-256
  `6cf420232c0ae432ac9f2471670916d93d7f440fc144b9adfea4509ca41a4e92`.
  The cross-bound public snapshot has byte SHA-256
  `1008b759bce54f22010316d408f7fc162a88204bf69bd18b8953119ff657d689`.
- Backlog alignment: HSSL-G160 remains active as one cohesive aggregate because source
  authentication, replay population selection and freshness, paired
  statistics, typed holdout missingness, traceability, and publication share
  one trust graph. The nonempty replay orchestrator and typed decision-domain
  attachment APIs are required bounded tasks within this goal before G170 can
  become executable. Generated
  external todo, objective-bundle, todo-vector, task-status, and supervisor
  backlog metadata remain supervisor-owned and were not manually edited;
  reconciliation is driven by HSSLEV1605D50, these canonical artifacts, the
  HSSL-BENCH-042 discovery receipt, and the exact validator.

## HSSL-G170 Publish the replacement evidence-bound architecture decision

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G160
- Fib priority: 832040
- Track: benchmark-reassessment
- Priority: P0
- Bundle: objective/hssl/reassessment-decision
- Goal: Publish a replacement Hammer/SyMAI/spaCy/Leanstral architecture decision and updated reproduction runbook only from a validated source-bound paired holdout and replay/report chain.
- Evidence: HSSLEV1703E61
- Outputs: docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision_v2.json, docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md, tests/unit/benchmarks/logic_pipeline/test_final_decision.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_final_decision.py -q; python benchmarks/logic_pipeline/report.py --validate-final-decision --artifact docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision_v2.json; python benchmarks/logic_pipeline/report.py --validate-runbook
- Acceptance: The replacement artifact is created only when the paired holdout gate and replay/report chain validate; it preserves and links the immutable v1 gather-more-evidence decision; selects or rejects every A0-A12/S1 arm and P0-P3 policy from measured evidence; assigns bounded component responsibilities; reports all quality, resource, and complexity tradeoffs; and never changes production routing or authorizes production promotion, which remains a separate reviewed action.
- Gap task: Publish the reassessment decision and runbook update without overwriting v1 evidence or promoting production automatically.
- Refinement depth: 1
- Follow-up source: `2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` required follow-up 6.
- Evidence implementation:
  `benchmarks.logic_pipeline.report.HSSLEV1703E61` is the stable AST evidence
  symbol for the source-bound replacement decision and updated reproduction
  runbook. `build_reassessment_final_decision` revalidates the immutable v1
  decision and the complete G130-G160 source graph before deriving any row;
  `validate_final_decision` recomputes the canonical v2 document and rejects
  source, disposition, missingness, or authorization drift; and
  `write_reassessment_final_decision` publishes canonical JSON while refusing
  an existing or symlinked destination by default. The CLI artifact selector
  and runbook validator expose the same evidence boundary.
- Immutable predecessor and source graph: The v1 gather-more-evidence decision
  remains unchanged at
  `docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision.json`.
  The v2 `supersedes` binding records it as a preserved immutable predecessor
  with semantic SHA-256
  `80823442e5115b2f499a2e77a11817dff555494ca0ecccfc79e59cbf423b7cce`
  and byte SHA-256
  `0e53798d3f1deaab040cf99f10034644f421ffd51f15090a948aa7085041a84e`.
  The replacement also authenticates the complete matrix
  (`437961214b97fadd495f65d4a006406b27086e6aeb9f46d8cd27e36df1ed39bb`),
  pilot gate
  (`2d146c1cb75eb8c2261a3e1be68ba98bf8b2a4996a1839fb36e26f9bd7f37acb`),
  holdout
  (`e408d7364209dde32ff4f987ba2845306ab226c2f442c0a3d4abfb18521ee44d`),
  replay index
  (`6248b875566afb7e9706c4f39d28e3a2eea680bd04dfd11f5fee6a5883af27d2`),
  statistics
  (`857bae66f9b336de82c6506b469b864f6bcfb1862a67142ba858695e85781b3d`),
  and dated reports
  (`91ba9aa88e48598c36d480c21552476bce454af9ca1449475fcab7785ec78fcf`)
  by their semantic identities. Their corresponding live byte SHA-256 values
  are
  `ad76be697eb084517354a9d2b82bf48378f33d820b6f6014a13d5a08bb105ac9`,
  `21713e069e063db32763f563f0184a7d7123a5e559527d54618fadc98d286a48`,
  `9e712b9ed1fb67c80115d12e3bc92850f23da601543fa59a4cbd700a54b0df9d`,
  `3fc20f5526b1ed9fe81eed52e3cd0bd17084b0a46361c37e25b6bc7236401649`,
  `6cf420232c0ae432ac9f2471670916d93d7f440fc144b9adfea4509ca41a4e92`,
  and
  `1008b759bce54f22010316d408f7fc162a88204bf69bd18b8953119ff657d689`.
- Measured disposition: The validated graph contains 560 pilot/development
  case results and 480 paired statistics observations, but every A1-A12
  candidate has zero independent-kernel-verified success and no independent
  semantic-quality observation. The pilot therefore froze an empty shortlist;
  the holdout remained `sealed_unopened`; and the valid replay population is
  empty with no replay claim. The ordered fourteen-row matrix retains A0 only
  as the current reference, rejects A1-A12 for this reassessment, and keeps S1
  diagnostic-only. All four P0-P3 policies are explicitly rejected because no
  eligible candidate or paired holdout evidence exists. This is measured
  rejection of the present candidates, not a claim that A0 won or that an
  experimental component can never be useful.
- Responsibilities and tradeoffs: spaCy is bounded to linguistic annotation,
  SyMAI to one pinned-router semantic or contract-repair attempt, Hammer to
  bounded deterministic search plus native reconstruction, and Leanstral to
  one bounded proof draft and reviewed repair. None receives a production
  responsibility. Safety, quality, latency, resources, reliability, routing,
  marginal escalation value, unnecessary calls, and complexity/Pareto are
  all structurally complete and source-bound. Applicable pilot/development
  values remain measured; all nine holdout domain values remain typed
  `not_applicable_before_authorization` nulls, never synthetic zero.
- Publication result: The canonical v2 artifact has semantic SHA-256
  `4742d8735c4b07b699f5f01049dec6d60305c4321f47e344c769eb21dcb6e0f2`
  and byte SHA-256
  `af14a16f7f72da0374a12b0b47c8ad58c0d2b707e6e8ffaf3a282cd260e05e3e`.
  Its outcome remains `gather_more_evidence`, with no selected variant or
  policy, no paired holdout efficacy, no replay claim, no production routing
  change, and no promotion or automatic merge authority. Any future
  production change remains a separately reviewed action requiring a canary
  and rollback plan.
- Backlog alignment: HSSL-G170 remains one cohesive aggregate because
  predecessor preservation, source authentication, arm and policy
  dispositions, component boundaries, tradeoff missingness, publication, and
  runbook traceability share one fail-closed trust graph. Splitting them would
  allow the decision or operating procedure to drift from its evidence, so no
  child goal or objective-heap refinement is needed. Generated external todo,
  objective-bundle, todo-vector, task-status, and supervisor backlog metadata
  remain supervisor-owned and were not manually edited; reconciliation is
  driven by HSSLEV1703E61, the canonical v2 artifact, the HSSL-BENCH-043
  discovery receipt, and the three exact validation commands.

## HSSL-G180 Evaluate one bounded Leanstral post-kernel repair in a new protocol and corpus revision

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G170
- Fib priority: 1346269
- Track: benchmark-protocol-revision
- Priority: P1
- Bundle: objective/hssl/leanstral-repair-revision
- Goal: Create an append-only protocol and reviewed corpus revision that can honestly measure one source-bound Leanstral repair after an independent native-kernel rejection without changing or reinterpreting revision 1.
- Evidence: HSSLEV1806D24
- Outputs: benchmarks/logic_pipeline/contracts.py, benchmarks/logic_pipeline/cases.py, benchmarks/logic_pipeline/adapters.py, tests/fixtures/logic_pipeline_benchmark_repair/corpus.jsonl, tests/fixtures/logic_pipeline_benchmark_repair/manifest.json, tests/integration/benchmarks/logic_pipeline/test_leanstral_repair_evaluation.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_leanstral_repair_evaluation.py tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py -q
- Acceptance: A new content-addressed protocol/corpus revision preregisters a nonempty, independently reviewed repair-eligible population before outcomes are observed; the first frozen draft is checked by the independent native kernel; only an allowlisted, bounded, source-bound diagnostic plus the failed draft can trigger exactly one repair against the identical obligation; the repair is checked in a separate kernel invocation; one-pass and repair arms retain complete efficacy, latency, resource, reliability, and failure receipts; a missing trigger remains typed and cannot become a success; and no revision 1 artifact, holdout input, production route, or promotion state changes.
- Gap task: Add a reviewed repair-trigger corpus extension and a post-kernel feedback edge in a new protocol revision, then run a fresh pilot/development-only comparison of one-pass synthesis against exactly one repair.
- Refinement depth: 1
- Follow-up source: The immutable diagnostic run `hssl-matrix-20260725T040701Z-21c385c72` retained zero repair attempts because the frozen revision 1 graph has no post-kernel feedback edge.
- Revision boundary: HSSL-G034 remains the transport and upper-bound contract; HSSL-G130 remains the immutable one-pass revision 1 measurement. HSSL-G180 must use new protocol, registry, corpus, prompt, run, cache, and capability-freeze identities and must never retrofit repair-trigger cases or results into revision 1.
- Scientific comparison contract: Case inclusion and the failure diagnostic schema are reviewed and frozen before model output. The exact first draft, first kernel rejection, sanitized diagnostic, repair request, second draft, and second kernel result form one provenance chain. Report the conditional conversion rate from kernel-rejected first drafts to accepted repairs and its full denominator alongside the extra model calls, tokens, wall time, memory, and failure classes; do not infer benefit from adapter support or from a zero-trigger population.
- Holdout boundary: HSSL-G180 is pilot/development research only. Any later holdout requires its own complete source-bound gate and exact nonempty authorization; the currently frozen holdout remains sealed.
- Backlog alignment: This is a bounded future protocol/corpus goal rather than unfinished HSSL-G034 adapter work. Generated todo-vector, objective-bundle, task-status, and discovery metadata remain supervisor-owned and must be regenerated from this heap rather than edited manually.

## HSSL-G190 Add a distinct source-bound legacy SymbolicAI S1 capability, bridge, and kernel-truth diagnostic

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G170
- Fib priority: 2178309
- Track: benchmark-diagnostic-revision
- Priority: P1
- Bundle: objective/hssl/legacy-symbolicai-diagnostic
- Goal: Determine whether the historical SymbolicAI implementation used by S1 can be recovered as a distinct pinned capability and, if so, compare its non-authoritative predictions with independent native-kernel truth without substituting modern SyMAI.
- Evidence: HSSLEV1904F81
- Outputs: benchmarks/logic_pipeline/capabilities.py, benchmarks/logic_pipeline/runtime.py, benchmarks/logic_pipeline/adapters.py, benchmarks/logic_pipeline/report.py, tests/integration/benchmarks/logic_pipeline/test_legacy_symbolicai_s1.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_legacy_symbolicai_s1.py tests/integration/benchmarks/logic_pipeline/test_matrix_reassessment.py -q
- Acceptance: A separate `legacy_symbolicai` capability records requested and effective package, engine, model/provider, configuration, source, and environment identities; a bounded bridge uses deterministic source-bound input projection, run-scoped cache isolation, resource limits, telemetry, and content-addressed receipts; predictions are joined only to an independent native-kernel truth receipt and remain excluded from primary efficacy, candidate selection, and proof authority; unavailable or unrecoverable historical identity stays typed unavailable; modern SyMAI or `llm_router` is never used as a substitute; revision 1 S1 records remain immutable; and no holdout or production activity occurs.
- Gap task: Recover and pin the historical SymbolicAI identity if it still exists, implement its isolated S1-only bridge and kernel-truth report, and otherwise publish a source-bound typed-unavailable capability receipt explaining why it cannot be reproduced.
- Refinement depth: 1
- Follow-up source: The immutable diagnostic run `hssl-matrix-20260725T040701Z-21c385c72` produced 40 intentional S1 unavailable outcomes through `legacy_symbolicai_identity_not_in_repaired_freeze`; this establishes missingness, not a current SymbolicAI performance result.
- Non-substitution contract: `SyMAI`, its current engine router, the shared Leanstral model identity, and legacy SymbolicAI are separate experimental identities even if they share ancestry or an endpoint. A current SyMAI call cannot close this goal, populate S1, or be described as legacy parity.
- Backward-compatibility contract: Frozen protocol revision 1 continues to deserialize and report S1 as diagnostic-only and may continue to emit its existing typed-unavailable result. The new capability and bridge must be additive under a new protocol/environment identity and cannot alter A0-A12 results, the immutable diagnostic run, or either published final-decision artifact.
- Holdout boundary: This goal may use only preregistered pilot/development diagnostic cases. S1 remains forever ineligible for the shortlist, and the currently frozen holdout remains sealed.
- Backlog alignment: This is a bounded future diagnostic goal distinct from the modern HSSL-G032 SyMAI adapter. Generated todo-vector, objective-bundle, task-status, and discovery metadata remain supervisor-owned and must be regenerated from this heap rather than edited manually.

## HSSL-G200 Establish the scoreable source-only semantic projection scaffold

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G170
- Fib priority: 3524578
- Track: benchmark-protocol-revision
- Priority: P0
- Bundle: objective/hssl/semantic-contract-revision
- Goal: Establish one bounded, label-blind normalized semantic projection that compiler, spaCy, and SyMAI can all emit and the independent semantic validator can score without consuming reviewed answers.
- Evidence: HSSLEV2007A42
- Outputs: benchmarks/logic_pipeline/contracts.py, benchmarks/logic_pipeline/ablation.py, benchmarks/logic_pipeline/runtime.py, benchmarks/logic_pipeline/adapters.py, benchmarks/logic_pipeline/semantic_reassessment.py, tests/unit/benchmarks/logic_pipeline/test_semantic_reassessment.py, tests/integration/benchmarks/logic_pipeline/test_semantic_projection_calibration.py
- Validation: python -m pytest tests/unit/benchmarks/logic_pipeline/test_semantic_reassessment.py tests/integration/benchmarks/logic_pipeline/test_semantic_projection_calibration.py tests/unit/benchmarks/logic_pipeline/test_symai_adapter.py -q
- Acceptance: A new protocol, registry, prompt, and schema digest preregister one canonical semantic projection with explicit logic, target, class, predicates, entities, completeness, and content digest fields; every producer derives it only from source text and producer evidence; `StageRequest.input_data` sent to compiler, spaCy, and SyMAI contains no expected IR/class, reviewed proof obligation, required label, or kernel outcome; compiler and spaCy normalize their real nested ModalIR fields; SyMAI's structured response requires every scored field and converts a vacuous candidate into an explicit typed semantic failure rather than either success or silent upstream fallback; validation errors have defined precedence over ambiguity; raw full-ModalIR hashes are never compared with differently shaped reviewed expected-IR hashes; and source-safe synthetic tests prove the schema, leakage, content-addressing, and fail-closed calibration boundaries without claiming that reviewed sources were executed.
- Gap task: Maintain and validate the semantic projection scaffold. HSSL-G201 owns the real source-replayed pilot/development calibration, and later execution goals own the measured matrix.
- Refinement depth: 1
- Follow-up source: The immutable diagnostic run `hssl-matrix-20260725T092337Z-3aeabda93` produced 240 source-bound semantic receipts, but none contained an observable target; live ModalIR and SyMAI schemas cannot emit the fields required by the revision 1 scorer, so its apparent `0.0` quality rate is unidentifiable rather than a valid all-model efficacy result.
- Leakage boundary: `expected_ir`, `expected_class`, required labels, reviewed `proof_obligation`, `compiled_obligation.semantic_target`, native certificates, and kernel outcomes may enter only the post-execution evaluator or proof trust boundary explicitly assigned to them. They must never populate the producer projection, model prompt, cache key semantic content, or upstream front-end context. Adversarial tests must prove that forged reviewed fields cannot improve a producer score.
- Revision boundary: Revision 1 receipts, prompts, registry, thresholds, and published decisions remain immutable diagnostics. Because the producer schema, SyMAI prompt, metric calibration, and eligibility behavior change, the repair requires a new protocol digest, run ID, capability freeze, cache namespace, full 520-coordinate A0-A12 pilot/development matrix, separately identified S1 diagnostic work, and an independent semantic receipt graph; no revision 1 result may be relabeled or reused as revision 2 efficacy.
- Gate boundary: Universal missing target/logic coverage or an all-zero score produced by an uncalibrated schema is `semantic_schema_incompatible`, not complete measured quality. Candidate selection requires complete calibrated semantic evidence plus a non-vacuous absolute quality condition before relative near-best comparisons can apply. Any calibration failure freezes an empty shortlist and keeps holdout closed.
- Holdout boundary: HSSL-G200 is data-free scaffold work. It must not inspect or execute any benchmark case, and it cannot authorize production routing or promotion.
- Backlog alignment: `HSSLEV2007A42` proves only the source-only semantic protocol scaffold. It must not suppress the separately bounded HSSL-G201 source-replay goal. Generated supervisor task-status, objective-bundle, todo-vector, and discovery metadata remain supervisor-owned and must be regenerated from this objective rather than manually edited.

## HSSL-G201 Execute and independently revalidate semantic calibration

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G202, HSSL-G220
- Fib priority: 5702887
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/semantic-calibration-execution
- Parallel lane: objective/hssl/semantic-calibration-execution
- Goal: Execute the G202-frozen source-only semantic submatrix over the complete reviewed, unsealed pilot/development set and independently replay every scoreability and leakage claim without changing the frozen revision after observing results.
- Evidence: HSSLEV2014B63
- Completion authority: external
- Outputs: an external run-scoped 20-case/100-coordinate calibration package, full semantic evidence index, calibration report, and independent validation receipt
- Validation: replay every persisted producer projection and calibration observation from the isolated pilot/development source package without using a combined holdout-capable loader
- Acceptance: Exactly the twenty reviewed pilot/development cases and every frozen calibration producer/cache coordinate are terminal and source-bound; all scored fields are representable; non-vacuous coverage and the preregistered calibration threshold pass; validation-error precedence and leakage controls replay; compiler, spaCy, and SyMAI evidence retains exact environment and provider identities; no reviewed answer enters a producer request or cache key; every record uses the revision-2 CID contract; an independent validator reproduces the complete calibration result; and no holdout path, source, label, obligation, or outcome is opened.
- Gap task: Run and independently revalidate the real unsealed pilot/development semantic submatrix under the exact G202 freeze, preserving complete per-coordinate receipts and an explicit failure result if any source or environment binding is missing.
- Refinement depth: 2
- Holdout boundary: HSSL-G201 may access only the separately loaded pilot/development calibration sources. It cannot load a combined corpus, inspect holdout, freeze a shortlist, or authorize production.
- Freeze boundary: G201 results are part of the preregistered selection evidence, not a tuning oracle. Any schema, prompt, route, threshold, or implementation change after a G201 observation retires the complete G202 run and requires a new protocol/run identity rather than a convenient rerun.
- Backlog alignment: This operational child remains unfulfilled until the
  independently governed HSSL-G220 replacement seal exists and the real source
  replay and independent validation receipts exist.  Requiring G220 first
  prevents G201 outcomes from influencing holdout authorship.  Synthetic
  HSSL-G200 tests, the scaffold evidence marker, and a self-asserted G202
  environment cannot satisfy it.

## HSSL-G210 Establish the fail-closed causal proof runtime scaffold

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G200
- Fib priority: 5702887
- Track: benchmark-protocol-revision
- Priority: P0
- Bundle: objective/hssl/causal-proof-revision
- Goal: Establish the additive, data-free causal proof protocol and single-case runtime boundary that removes the A0-versus-candidate verification confound and permits Hammer or Leanstral credit only for a distinct independently accepted rescue.
- Evidence: HSSLEV2108F34
- Outputs: benchmarks/logic_pipeline/contracts.py, benchmarks/logic_pipeline/cases.py, benchmarks/logic_pipeline/variants.py, benchmarks/logic_pipeline/runtime.py, benchmarks/logic_pipeline/metrics.py, benchmarks/logic_pipeline/statistics.py, tests/integration/benchmarks/logic_pipeline/test_causal_proof_ablation.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_causal_proof_ablation.py tests/integration/benchmarks/logic_pipeline/test_live_runtime.py tests/unit/benchmarks/logic_pipeline/test_statistics.py -q
- Acceptance: The source-bound protocol, variant profiles, compiler-reference exposure, causal candidate-selection receipts, duplicate suppression, identical native-kernel policy, typed failure accounting, component telemetry, and full single-case `CausalRuntimeEvidenceV2` replay validate on synthetic inputs; the retired selection-only batch wrapper fails closed; and neither this scaffold nor its evidence marker claims that an authoritative batch matrix or reviewed rescue-population run exists.
- Gap task: Maintain and validate the fail-closed single-case causal runtime scaffold. HSSL-G211 owns authoritative full-evidence batch persistence and HSSL-G212 owns the real reviewed rescue-matrix execution.
- Refinement depth: 1
- Follow-up source: In `hssl-matrix-20260725T092337Z-3aeabda93`, A0 emitted the same compiler-native candidate population but never invoked the kernel, every A1-A12 arm had the identical 18-of-40 verified set, all 216 accepted receipts selected compiler candidates, and 168 Hammer results duplicated the compiler certificate. Direct Leanstral produced no selected candidate.
- Routing boundary: Hammer runs only after a valid deterministic obligation lacks an accepted compiler proof. Leanstral runs only after the preregistered deterministic failure condition assigned to its arm. SyMAI semantic work cannot receive proof credit, and neither solver nor model verdict can replace the native-kernel receipt.
- Model-service boundary: SyMAI and direct Leanstral share a single source-bound provider/service lease and cache coordinator when their frozen inner provider, model, and endpoint identities are identical, while retaining distinct semantic versus proof prompts, cache keys, telemetry, and stage receipts.
- Holdout boundary: HSSL-G210 is data-free scaffold work. It cannot inspect benchmark inputs, access holdout, authorize a shortlist, or change production routing.
- Backlog alignment: `HSSLEV2108F34` proves only the causal runtime scaffold. It must not suppress the separately bounded HSSL-G211 persistence and HSSL-G212 execution goals. Generated supervisor metadata must be regenerated from this goal and its tests.

## HSSL-G211 Persist authoritative full G210 runtime evidence

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G210
- Fib priority: 9227465
- Track: benchmark-protocol-revision
- Priority: P0
- Bundle: objective/hssl/causal-runtime-batch
- Parallel lane: objective/hssl/causal-runtime-batch
- Evidence: HSSLEV2116C82
- Goal: Persist every complete `CausalRuntimeEvidenceV2` receipt and compile a source-revalidated `G210ReceiptMatrix` without reducing native-kernel, telemetry, resource, or provenance evidence.
- Outputs: benchmarks/logic_pipeline/causal_batch.py, benchmarks/logic_pipeline/causal_runtime.py, benchmarks/logic_pipeline/revised_pilot_authorization.py, tests/integration/benchmarks/logic_pipeline/test_causal_runtime_batch.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_causal_runtime.py tests/integration/benchmarks/logic_pipeline/test_causal_runtime_batch.py tests/integration/benchmarks/logic_pipeline/test_revised_pilot_authorization.py -q
- Acceptance: Batch execution, persistence, resume, and replay bind every scheduled coordinate to its full runtime-evidence CID; the matrix binds and revalidates every complete receipt rather than only a reduced selection receipt or aggregate; G240 runtime-namespace and source-orchestration evidence sets are validated before the first write, persisted beside the canonical coordinate envelopes, reread on resume, and bound into the batch result; the output root is absolute, private, outside every Git repository/worktree, symlink-safe, and creates private run directories; missing, duplicated, reduced, source-mismatched, kernel-unreplayable, foreign, orchestration-rebased, or insecure-path evidence fails closed; and no fixture, corpus, or holdout content is required to validate the bridge.
- Gap task: Maintain the implemented full-evidence persistence bridge and require its G240 namespace/source-orchestration sets at every operational G231 consumer; the real matrix remains HSSL-G212 work.
- Evidence implementation: `benchmarks.logic_pipeline.causal_batch.HSSLEV2116C82` names the write-once full-evidence boundary. `persist_causal_runtime_batch_v2` replays the complete batch before its first filesystem write, derives and binds the compiler-reference population and causal aggregates, validates the associated `G240RuntimeNamespaceEvidenceSetV2` and `G240SourceOrchestrationEvidenceSetV2` against their private source inputs, and persists those sets with one canonical envelope per exact plan coordinate under advisory locks. `validate_causal_runtime_batch_v2` rereads every typed record and rejects foreign, truncated, noncanonical, source-rebased, profile-rebound, orchestration-rebound, or reduced evidence. `G210RuntimeReceiptMatrixV2` and `build_g210_runtime_receipt_matrix_v2` provide the two-split full-runtime join required by G212/G231 without treating reduced aggregates as runtime authority.
- Implementation result: The source-safe synthetic G211 suite covers complete persistence, immutable resume, concurrent convergence, full-evidence tampering, foreign records, profile/population drift, proof-context drift, incomplete job maps, and G240 namespace/source-orchestration persistence. Compatibility callers may omit G240 sets for bounded legacy synthetic tests, but G231 requires non-null live sets for both operational split batches. This closes the persistence implementation slice only; it is not evidence that real G201 sources were replayed or that G212 executed.
- Refinement depth: 2
- Holdout boundary: This implementation goal uses synthetic cases only and cannot authorize or access holdout.
- Backlog alignment: The `HSSLEV2116C82` implementation marker names the complete source-safe persistence boundary only; it cannot stand in for a real G201/G212 matrix, live G240 evidence, or external operational receipt. Generated supervisor metadata must be regenerated from this child goal rather than inferred from HSSL-G210.

## HSSL-G212 Execute and revalidate the frozen causal pilot/development submatrix

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G201, HSSL-G211, HSSL-G202
- Fib priority: 14930352
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/causal-rescue-matrix
- Parallel lane: objective/hssl/causal-rescue-matrix
- Evidence: HSSLEV2123D59
- Completion authority: external
- Goal: Continue the one G202-frozen pilot/development plan from its persisted G201 semantic evidence through the authoritative HSSL-G211 causal batch bridge, without re-invoking front ends or creating a second selection run.
- Outputs: an external run-scoped G210 matrix, full runtime-evidence index, causal aggregates, independently measured operational-resource receipts, reviewed control-index joins, and an independent validation receipt
- Validation: validate every persisted CausalRuntimeEvidenceV2 and the complete G210ReceiptMatrix from source in the isolated run namespace
- Acceptance: Every required A0-A12 arm, case, split, and cache coordinate in the exact frozen plan is terminal and source-bound; every route consumes the matching immutable G201 source-only front-end record; A0 and candidates receive identical external kernel exposure; optional-component rescue is causally attributable; duplicate certificates receive zero marginal credit; every efficacy, suppression, escalation, cost, and resource denominator is complete; independent resource receipts retain solver-process and accelerator-use evidence rather than inferred zeros; the reviewed non-holdout control index covers every required safety coordinate; and the external validator replays all full evidence CIDs without inspecting holdout.
- Gap task: Execute and independently revalidate the real reviewed pilot/development causal submatrix only after the frozen G201 semantic submatrix and HSSL-G211 persistence validate.
- Refinement depth: 2
- Holdout boundary: HSSL-G212 is pilot/development-only and cannot access holdout, freeze a shortlist, or authorize production.
- Freeze boundary: G212 completes the measured execution started by G201 under the same G202 source, run plan, environment, cache policy, and namespaces. It may not reinterpret failures, change candidate routes, or trigger a fresh semantic pass.
- Backlog alignment: Operational matrix evidence is distinct from the HSSL-G210 scaffold marker. Generated task state must retain dependencies on HSSL-G201, HSSL-G211, and HSSL-G202 and must not treat synthetic tests as a measured benchmark run.

## HSSL-G220 Replace and independently reseal the benchmark holdout

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G202
- Fib priority: 9227465
- Track: benchmark-holdout-revision
- Priority: P0
- Bundle: objective/hssl/replacement-holdout
- Goal: Retire the current holdout from future selection claims and create a newly reviewed, independently authored, access-controlled holdout only after HSSL-G202 freezes the complete revision-2 protocol, prompts, metrics, routes, thresholds, source, and runtime identities but before pilot/development outcomes can influence its contents.
- Evidence: HSSLEV2205C73
- Completion authority: external
- Outputs: a content-addressed sealed-manifest identity and public count/strata receipt outside the tuning worktree, an access-controlled holdout corpus outside the tuning worktree, benchmarks/logic_pipeline/cases.py, benchmarks/logic_pipeline/holdout_execution.py, tests/integration/benchmarks/logic_pipeline/test_replacement_holdout_seal.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_replacement_holdout_seal.py tests/integration/benchmarks/logic_pipeline/test_authorized_holdout_execution.py -q
- Acceptance: The old holdout is permanently ineligible for a new efficacy or promotion claim; the replacement cases and labels are authored and reviewed by a party isolated from protocol tuning; only a content-addressed sealed manifest and strata/count metadata are visible before authorization; tuning agents cannot load source text, labels, expected IR, proof obligations, or outcomes; every access is append-only receipted; exact A0 and frozen-shortlist paired execution is impossible before HSSL-G241 validates the complete HSSL-G232 pilot artifact and releases its exact authorization to the custodian; and any premature access invalidates the replacement rather than being converted into a clean seal.
- Gap task: Arrange independent replacement-holdout authorship and review, implement an access-controlled loader and append-only access receipt, then freeze its identity after the revised protocol and before any authorized evaluation.
- Refinement depth: 1
- Follow-up source: During post-run diagnosis, the combined fixture layout proved capable of exposing holdout source and reviewed labels outside the holdout access logger. Even though no holdout backend execution or result artifact occurred, that confidentiality boundary is insufficient for a future blinded claim.
- Isolation boundary: The replacement holdout must not reside in a plainly readable combined corpus inside the tuning worktree. The supervisor may schedule and verify seal mechanics, but it must not generate answer labels, summarize hidden cases, or expose them to any agent that modified HSSL-G200.
- Publication boundary: HSSL-G220 creates no shortlist, efficacy claim, production routing change, or promotion. HSSL-G232 must later join the already frozen G201/G212 pilot/development evidence and freeze a nonempty eligible shortlist, and HSSL-G241 must independently validate and release that exact authorization before a revision-2 executor may open the replacement holdout.
- Backlog alignment: This is a separate trust-boundary goal because independent authorship, confidentiality, access logging, and invalidation cannot be satisfied by the HSSL-G200, HSSL-G210, HSSL-G211, or HSSL-G212 implementation agents. Generated supervisor metadata must be reconciled from this objective without copying hidden holdout contents into the task board.

## HSSL-G230 Establish the negative-only revised-pilot authorization scaffold

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G211
- Fib priority: 14930352
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/revised-pilot-authorization
- Goal: Establish a persistable, source-bound negative readiness artifact over the revision-2 public schemas that is structurally incapable of minting a positive shortlist or replacement-holdout authorization until source-recomputed gate validators and operational evidence exist.
- Evidence: HSSLEV2309D46
- Outputs: benchmarks/logic_pipeline/revised_pilot_authorization.py, tests/integration/benchmarks/logic_pipeline/test_revised_pilot_authorization.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_revised_pilot_authorization.py -q
- Acceptance: Malformed, incomplete, reduced, stale, source-mismatched, or self-asserted dependencies emit stable failure codes and an empty shortlist; gate receipt CIDs and positive authorization are structurally absent; holdout outcomes remain uninspected; and `HSSLEV2309D46` proves only this negative scaffold, not pilot execution or eligibility.
- Gap task: Maintain the fail-closed negative decision boundary. HSSL-G234 through HSSL-G238 own independent validator slices, HSSL-G231 composes them, HSSL-G232 owns the final pilot evidence join, and HSSL-G241 owns the externally governed custodian-release decision.
- Refinement depth: 1
- Authorization boundary: This goal can authorize nothing. Its schema tests use only synthetic identities and do not depend on or establish actual HSSL-G201, HSSL-G212, or HSSL-G220 operational evidence.
- Holdout boundary: Revision-1 HSSL-G150 and its old holdout must never be reused for a revision-2 claim. HSSL-G230 cannot open any replacement holdout.
- Backlog alignment: `HSSLEV2309D46` proves only the negative scaffold and must not suppress HSSL-G231, HSSL-G232, or HSSL-G241. Generated supervisor metadata must not infer authorization from this goal's completion.

## HSSL-G234 Implement full-runtime efficacy, reliability, and routing validators

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G230
- Fib priority: 14930352
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/full-runtime-gates
- Parallel lane: objective/hssl/full-runtime-gates
- Evidence: HSSLEV2343B16
- Goal: Recompute paired proof efficacy, reliability, and routing from every full `CausalRuntimeEvidenceV2` receipt while keeping split/cache cells separate and preserving unavailable or infrastructure outcomes as null rather than zero.
- Outputs: benchmarks/logic_pipeline/revised_pilot_authorization.py, tests/integration/benchmarks/logic_pipeline/test_revised_pilot_positive_gates.py
- Validation: python -m pytest tests/integration/benchmarks/logic_pipeline/test_causal_runtime_batch.py tests/integration/benchmarks/logic_pipeline/test_revised_pilot_positive_gates.py -q
- Acceptance: Every A0/candidate pair binds the same run, case, split, cache, source, proof context, case manifest, compiler exposure, and exact runtime receipt CIDs; measured verified/nonverified outcomes remain distinct from missing outcomes; candidate wins, A0 regressions, both/neither counts, typed failures, retries, optional routing, suppression, duplicate overlap, and equal external verification exposure recompute from source; tampered or reduced evidence fails closed; and no efficacy threshold or safety classification is invented by this slice.
- Gap task: Complete the CID-native full-runtime gate family and focused synthetic recomputation tests without claiming semantic quality, safety, cost, statistics, Pareto, or detached replay.
- Evidence implementation: `benchmarks.logic_pipeline.revised_pilot_authorization.HSSLEV2343B16` binds this goal to the three source-recomputed full-runtime gates. The efficacy gate retains separate split/cache A0 pairs and null missing outcomes; reliability replays terminal and recovered typed failures; routing replays optional triggers, invocation, suppression, overlap, duplicate work, native checks, and the mandatory shared compiler row. Exact runtime, case-result, source, proof-context, rescue-manifest, compiler-exposure, and variant-profile CIDs are bound throughout, while the legacy case-manifest SHA field remains only as an explicit compatibility join.
- Implementation result: Source-safe complete, partial, tamper, unequal-exposure, route-substitution, schema-boundary, and invalid-candidate tests pass. This establishes validator implementation only; no real G201/G212 evidence has passed an efficacy, reliability, or routing threshold.
- Refinement depth: 3
- Holdout boundary: Source-safe validator implementation cannot inspect or authorize holdout.
- Backlog alignment: This bounded slice may complete in parallel with HSSL-G235 through HSSL-G238. Its evidence marker proves only the full-runtime gate family and cannot satisfy the HSSL-G231 composite.

## HSSL-G235 Implement source-recomputed semantic-quality validation

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G230
- Fib priority: 24157817
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/semantic-quality-gate
- Parallel lane: objective/hssl/semantic-quality-gate
- Evidence: HSSLEV2350C27
- Goal: Bind the complete G201 semantic target/projection graph and per-arm semantic observations to one source-recomputed quality gate without trusting a calibration artifact CID as truth.
- Outputs: benchmarks/logic_pipeline/semantic_reassessment.py, benchmarks/logic_pipeline/semantic_quality.py, benchmarks/logic_pipeline/revised_pilot_authorization.py, tests/integration/benchmarks/logic_pipeline/test_semantic_quality_source_replay.py, tests/integration/benchmarks/logic_pipeline/test_revised_pilot_positive_gates.py
- Validation: run source-safe synthetic semantic-gate tests; operational passage remains unavailable until G201 emits the real reviewed source package and receipt graph
- Acceptance: The validator replays the reviewed target manifest, every label-blind producer projection, every runtime semantic observation, exact source/environment/protocol identities, non-vacuous absolute quality, coverage denominators, and validation-error precedence; a raw CID, reduced report, absent target, missing arm, or post-freeze prompt/schema change fails closed; and no producer receives reviewed answers.
- Gap task: Add a portable semantic source index and per-arm semantic-quality gate that can consume G201 output without opening holdout.
- Evidence implementation: `benchmarks.logic_pipeline.semantic_quality.HSSLEV2350C27` binds the portable full-source G201 evidence index and G235 gate. The index strictly reparses the reviewed pilot/development target and split identities, two exact source-only calibration plans, all 100 full `CaseResultRecord` values, every frozen producer route and stage prefix, and the resulting five-field observations before independently rebuilding the complete calibration report. The gate then joins that source-recomputed index to every selected A0/candidate, split, cache, and rescue-case coordinate in `G210RuntimeReceiptMatrixV2`; it never treats the report CID, a reduced aggregate, or a caller-provided score as authority.
- Quality and leakage contract: G201 must first pass its preregistered complete 20-case absolute-quality and Wilson condition. Every selected runtime arm must separately have complete, non-vacuous observations and meet the same frozen `SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2` floor; missing evidence remains null while a validation-error-precedence result remains a measured zero. Precedence handling is source-verified on every scheduled runtime coordinate, independently of the count on which it was triggered. Producer inputs replay as exactly `{"text": source_text}`. SyMAI cache namespaces and keys are reconstructed from their complete label-blind prompt/schema/registry/source/provider/model/inner-route preimages, and requested/effective identity CIDs remain bound. Revision-1 manifest and record SHA-256 fields are compatibility joins only; the new index, source coordinates, observations, reports, variant profiles, and gate receipts are CID-addressed.
- Implementation result: Source-safe synthetic tests cover a complete pass, complete G201 absolute-quality failure, per-arm below-floor failure, validation-error measured-zero precedence, absent reviewed targets, missing arms/coordinates, report-only and reduced inputs, forged reviewed fields, producer-label leakage, cache-key tampering, prompt/projection-schema/route drift, and derived gate rebasing. No test opens fixture, corpus, manifest-path, or holdout content, and this validator implementation does not satisfy the external operational HSSL-G201 run.
- Refinement depth: 3
- Holdout boundary: Synthetic validation uses no fixture, corpus, manifest, or holdout content; operational G201 input remains pilot/development-only.
- Backlog alignment: This lane is independent of proof efficacy and resource accounting and may proceed in parallel.

## HSSL-G236 Implement reviewed-control safety authority

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G230
- Fib priority: 39088169
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/reviewed-control-safety
- Parallel lane: objective/hssl/reviewed-control-safety
- Evidence: HSSLEV2367D38
- Goal: Define a CID-addressed, independently reviewed non-holdout control index and recompute the fatal native-kernel false-positive gate from exact runtime receipts instead of caller-supplied booleans.
- Outputs: benchmarks/logic_pipeline/cases.py, benchmarks/logic_pipeline/reviewed_control.py, benchmarks/logic_pipeline/revised_pilot_authorization.py, tests/integration/benchmarks/logic_pipeline/test_reviewed_control_safety.py, tests/integration/benchmarks/logic_pipeline/test_revised_pilot_positive_gates.py
- Validation: run source-safe synthetic control-index and safety-gate replay tests without loading the legacy combined corpus
- Acceptance: Every control entry binds case, split, source CID, control kind/policy classification, review attestation, source/rescue manifests, and `holdout_included=false`; every required runtime coordinate joins exactly one classification; safety counts terminal independent-kernel acceptance rather than model/solver claims; a nonempty fully observed invalid-control population with zero acceptances passes; any kernel acceptance is fatal; and missing, forged, stale, or caller-asserted classifications are incomplete.
- Gap task: Implement the reviewed control-index schema, batch join, fatal safety validator, and tamper tests.
- Evidence implementation: `benchmarks.logic_pipeline.reviewed_control.HSSLEV2367D38` binds typed CID-native control attestations, entries, indexes, fixed A0-A12/cold-warm coordinates, terminal native-kernel replay, and a source-recomputed safety-gate receipt. Review and execution authority identities must differ; classifications bind source and rescue manifests; and runtime or metric booleans never become classification authority.
- Implementation result: Source-safe tests cover a complete zero-acceptance pass, fatal independently verified acceptance, missing/duplicate/unexpected coordinates, forged/stale attestations and manifest bindings, same-authority review, holdout claims, bare-SHA substitutions, raw caller assertions, and gate rebasing. Operational passage still requires an independently frozen complete control-index CID; a smaller internally valid index cannot establish that no reviewed control was omitted.
- Refinement depth: 3
- Holdout boundary: The control index is explicitly non-holdout and must remain independently reviewable without revealing replacement-holdout contents.
- Backlog alignment: Safety authority is a separate trust boundary and may not be inferred from semantic class names or `EfficiencyObservation.invalid_control`.

## HSSL-G237 Implement independent resource, cost, statistics, and Pareto validation

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G230
- Fib priority: 63245986
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/resource-statistics-gates
- Parallel lane: objective/hssl/resource-statistics-gates
- Evidence: HSSLEV2374E49
- Goal: Join each full runtime receipt to independent operational-resource evidence, paired statistical strata, and a source-recomputed safety-preserving Pareto analysis without treating missing work as zero cost.
- Outputs: benchmarks/logic_pipeline/metrics.py, benchmarks/logic_pipeline/statistics.py, benchmarks/logic_pipeline/resource_statistics.py, benchmarks/logic_pipeline/revised_pilot_authorization.py, tests/integration/benchmarks/logic_pipeline/test_resource_statistics_gate.py, tests/integration/benchmarks/logic_pipeline/test_revised_pilot_positive_gates.py
- Validation: run source-safe synthetic resource/statistics/Pareto recomputation and tamper tests
- Acceptance: CID-native resource receipts bind runtime receipt, environment, component wall time, peak memory, model calls, retries, solver processes, accelerator minutes, queue delay, and release/reap state; paired requests retain exact A0/candidate case/stratum links with missingness; cost and efficacy remain separate; the Pareto frontier is direction-aware and safety-feasible; null resource fields make the gate incomplete; and every aggregate and frontier identity replays from source.
- Gap task: Extend or replace the legacy SHA-oriented resource boundary with CID-native independent receipts and implement paired statistics, cost, and Pareto validators.
- Evidence implementation: `benchmarks.logic_pipeline.resource_statistics.HSSLEV2374E49` binds independently metered component receipts to exact full-runtime, raw-source, CID-wrapped frozen-environment, run, and coordinate identities. Producer, meter, and validator identities are pairwise distinct; missing numeric or lifecycle fields retain nonempty reasons; A0/candidate cost pairs retain source-derived strata and exact runtime/resource receipt CIDs; the existing seeded paired-bootstrap primitive is replayed through a CID-native projection; efficacy and cost have separate aggregate CIDs; and safety remains a hard, pinned G236 receipt constraint in the direction-aware Pareto recomputation.
- Implementation result: Source-safe synthetic tests cover complete passage, CID round trips, no new bare-SHA fields, null wall-time and queue-delay preservation, missing/duplicate/stale/rebased resource populations, distinct-authority enforcement, release/reap failure, statistically unpaired evidence, G236 state/CID rebasing, direction-aware non-dominance, and aggregate/frontier tampering. G237 validates only the pinned G236 receipt reference; HSSL-G231 must separately source-replay the complete G236 control index, manifests, and runtime population before composition. Operational passage still requires an independently frozen resource-evidence-set CID and real pilot/development receipts.
- Refinement depth: 3
- Holdout boundary: Source-safe validator tests cannot inspect holdout; operational evidence remains pilot/development-only.
- Backlog alignment: This lane owns operational cost authority that `CausalRuntimeEvidenceV2` telemetry alone cannot supply.

## HSSL-G238 Implement fresh detached execution replay validation

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G230
- Fib priority: 102334155
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/detached-replay-gate
- Parallel lane: objective/hssl/detached-replay-gate
- Evidence: HSSLEV2381F50
- Goal: Implement the validator and executor boundary that upgrades
  receipt-only replay assessment into bounded fresh detached execution replay
  over every success and a preregistered failure sample under isolated process,
  state, and cache namespaces.
- Outputs: benchmarks/logic_pipeline/replay.py, benchmarks/logic_pipeline/replay_gate.py, benchmarks/logic_pipeline/revised_pilot_authorization.py, tests/integration/benchmarks/logic_pipeline/test_revised_pilot_positive_gates.py, tests/integration/benchmarks/logic_pipeline/test_fresh_replay_gate.py, tests/integration/benchmarks/logic_pipeline/test_fresh_worktree_replay.py
- Validation: run source-safe synthetic replay-gate tests plus disposable-repository detached replay tests
- Acceptance: Replay uses the exact source commit, recursive gitlinks, environment, routes, cases, and receipts but a different detached worktree, run ID, process namespace, private state/output roots, and per-stage cache namespaces; every replay is an actual bounded process-group execution whose command and tracked entrypoint source match the G202-frozen `G240SourceExecutorContractV2`; private validation sources re-open the live source and replay worktrees and exact canonical evidence bytes; every success and the deterministic sampled failures reproduce the required semantic, kernel, status, and resource identities; same-run, attached, stale, precomputed, partial, or receipt-only replay remains incomplete; and no merge or holdout access occurs.
- Gap task: Complete the final local G231 parent integration and full regression
  suite for the replay implementation. HSSL-G243 separately owns supplying and
  externally validating real G201/G212 replay inputs after the run gates permit
  them.
- Evidence implementation: `benchmarks.logic_pipeline.replay_gate.HSSLEV2381F50` binds a CID-native source record/index, all-success plus deterministic per-split/cache/variant failure-stratum selection, per-target detached replay receipts, and a source-recomputed positive gate. `run_g240_detached_replay_v2` performs the actual detached bounded process execution; `G240PrivateReplayValidationSourcesV2` revalidates live worktrees, requests, receipts, canonical runtime bytes, namespaces, and the frozen executor contract. Git object IDs remain explicitly typed Git identities and are separately addressed by CID instead of being presented as bare content authority.
- Implementation result: The source-safe path requires operational private replay sources and rejects a receipt-only claim even when its public CIDs are internally consistent. Tests cover the complete population, deterministic failure sampling, exact semantic/native-kernel/status/resource equality, disposable detached Git worktrees, source/index/receipt round trips, stale source, same-run or attached execution, shared worktree/process/state/cache identities, executor-contract or entrypoint drift, partial evidence, authority overlap, holdout access, bare-digest substitution, and gate rebasing. Final parent integration and the complete regression suites remain open; no real G201/G212 result has yet undergone fresh replay.
- Refinement depth: 3
- Holdout boundary: Pilot/development replay remains holdout-free and cannot authorize production.
- Backlog alignment: This implementation lane may proceed independently after
  the negative G230 scaffold and joins locally at HSSL-G231. Its operational
  use and completion authority join later at HSSL-G243.

## HSSL-G239 Implement typed external operational-completion authority

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G230
- Fib priority: 165580141
- Track: benchmark-supervision
- Priority: P0
- Bundle: objective/hssl/external-completion-authority
- Parallel lane: objective/hssl/external-completion-authority
- Evidence: HSSLEV2398A61
- Goal: Make the agent supervisor reconcile operational benchmark goals only from typed, source-bound external completion receipts instead of treating evidence-marker text or locally generated task metadata as proof that an external run completed.
- Outputs: ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor external-completion receipt and reconciliation support, focused supervisor tests, and a documented external receipt schema
- Validation: run focused source-safe supervisor completion/reconciliation tests with synthetic external artifact identities
- Acceptance: A completion receipt binds the exact goal and evidence term, clean outer commit and tree, recursive gitlinks, immutable run-plan identity, parent-completion ledger, every required external artifact CID, and an independent validator receipt CID; stale, dirty, partial, duplicated, marker-only, self-asserted, or source-mismatched evidence fails closed; only canonical identities and public metadata enter supervisor storage; no external source, label, manifest, proof obligation, or holdout content is copied into the repository or task board; and completion never follows merely from finding the evidence term in source text.
- Gap task: Preserve the typed external-completion adapter and its canonical
  scheduler fence, then supply operational authority only through an explicit
  out-of-repository receipt path. Marker scanning remains implementation
  discovery and never becomes operational authority.
- Evidence implementation: Submodule commits `cf1e8efd`, `03a90b35`,
  `5bec6c80`, and `9c34535d` add typed canonical-CID requirements,
  operational receipts, current-source inspection, external authority
  evaluation, two-phase completion evidence, the bounded
  `HSSLEV2398A61` implementation marker, explicit daemon reconciliation,
  first-ingestion governance for goals declaring
  `Completion authority: external`, and mandatory revalidation of every
  asserted `verified_complete` state. Nested supervisor commit `2696e5ca`
  hardens that provenance with four additional safety fixes: wrapped objective
  fields and their rewrites preserve the complete goal/output/validation/
  acceptance/gap text; current tracked source, symbols, tokens, embeddings,
  and AST fields are fully recomputed instead of trusting a persisted AST row;
  declaration aliases, durable authority CIDs, and typed
  `external_operational_completion` evidence share one sticky external-
  authority fence; and caller-supplied duplicate task CIDs merge only for
  semantically equivalent work, while conflicts emit
  `conflicting_duplicate_task_identity` even if either copy claims success.
- Implementation result: Source-safe tests cover complete and absent receipts,
  marker-only evidence, dirty objective state, dirty or wrong-HEAD recursive
  gitlinks, stale/partial/duplicate/unexpected identities, noncanonical
  multiformats encodings, producer/validator overlap, migration rewrites,
  omitted authority, configured no-read exclusions, path-disclosure
  resistance, wrapped-field preservation, poisoned persisted-AST rows, sticky
  authority aliases, and conflicting duplicate task identities. The nested
  implementation validates identity consistency and current Git state;
  fetching CID payloads and verifying validator signatures remain
  responsibilities of the separately governed authority trust root, not the
  local supervisor or holdout custodian.
- Refinement depth: 3
- Holdout boundary: Synthetic tests use opaque CIDs and cannot inspect pilot/development or holdout content.
- Backlog alignment: HSSL-G201, HSSL-G202, HSSL-G203, HSSL-G212, HSSL-G220,
  HSSL-G232, HSSL-G241, HSSL-G242, and HSSL-G243 remain incomplete until
  their own valid external receipts exist. This implementation marker proves
  the completion-authority mechanism only.

## HSSL-G240 Bind runtime cache, process, and state namespaces to execution evidence

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G211, HSSL-G230
- Fib priority: 433494437
- Track: benchmark-remediation
- Priority: P0
- Bundle: objective/hssl/runtime-namespace-provenance
- Parallel lane: objective/hssl/runtime-namespace-provenance
- Evidence: HSSLEV2405D72
- Goal: Implement the fail-closed source executor and detached-replay boundary
  that can prove an operational revision-2 run's actual environment, cache
  keys, process group, persisted state, output namespace, and confinement came
  from the exact preregistered G202 policy rather than accepting opaque
  caller-supplied identities.
- Outputs: benchmarks/logic_pipeline/namespace_provenance.py,
  benchmarks/logic_pipeline/causal_batch.py,
  benchmarks/logic_pipeline/positive_gate_bundle.py,
  benchmarks/logic_pipeline/runtime_confinement.py,
  benchmarks/logic_pipeline/source_bootstrap_contract.py,
  benchmarks/logic_pipeline/source_bootstrap.py,
  benchmarks/logic_pipeline/source_bound_import.py,
  benchmarks/logic_pipeline/source_executor.py,
  benchmarks/logic_pipeline/source_orchestration.py,
  benchmarks/logic_pipeline/replay.py,
  benchmarks/logic_pipeline/replay_gate.py,
  tests/integration/benchmarks/logic_pipeline/test_runtime_confinement.py,
  tests/integration/benchmarks/logic_pipeline/test_source_orchestration.py,
  tests/integration/benchmarks/logic_pipeline/test_fresh_worktree_replay.py
- Validation: run synthetic execution, resume, concurrency, tamper, and detached-replay tests without loading benchmark cases or external artifacts
- Acceptance: Source-safe tests prove that the frozen policy derives disjoint
  cold/warm cache, process-group, state, output, and replay namespace CIDs from
  canonical preimages containing the source/run/plan/variant/stage/cache-mode
  identity required for that namespace; the production child uses an explicitly
  supplied and content-addressed pinned interpreter/runtime rather than ambient
  user site packages; its environment is an allowlist that rejects loader,
  Python, Git, and process-injection variables; Git and every required
  executable are absolute and source-bound; SyMAI configuration and logs are
  job-scoped; cache receipts distinguish actual prime/hit behavior from merely
  reserved physical directories; replay expectations derive from authenticated
  source execution; and a mandatory confinement policy denies protected or
  unapproved filesystem access while allowing TCP connect only to destination
  port 8080 for the already-running local model API and allowing no TCP bind.
  This port rule is not an IP-address authentication claim and is distinct
  from the separately operated G203 P2P listener on port 19001.
  G211 persists and replays these bindings, and G238 recomputes them in a
  different detached worktree/run namespace without requiring volatile values
  to be byte-identical. Missing, opaque, reused, cross-run, cross-mode,
  unscoped, path-leaking, caller-copied, unconstrained, or ambient-environment
  claims fail closed; no secret, source text, case label, manifest content,
  proof obligation, or holdout content enters a public receipt.
- Gap task: Keep the locally complete implementation regression-closed and
  supply its exact clean-source identities to G202. Operational validation of
  the actual G201/G212 process and namespace population belongs only to
  externally governed HSSL-G243.
- Evidence implementation: `namespace_provenance.py` defines canonical runtime
  and replay namespace preimages, receipts, recursive-gitlink projections, and
  private live-worktree validation sources. `runtime_confinement.py` defines
  the fail-closed Landlock ABI 6/7 filesystem, TCP-port, abstract-UNIX-socket,
  and signal policy and its path-free receipt.
  `source_bootstrap_contract.py` freezes the two-stage bootstrap profile,
  private-policy transport, exact TCP destination-port set `(8080,)`, and
  bootstrap receipt; `source_bootstrap.py` is the directly launched,
  single-threaded tracked stage that authenticates source/Git observations,
  rejects unexpected inherited descriptors, applies Landlock, emits one
  canonical one-shot pipe receipt, and only then delegates to stage two.
  `source_bound_import.py` resolves the exact pinned submodule modules without
  repeating Git after confinement. `source_executor.py` owns authenticated
  stage-two runtime import preflight and one-job execution.
  `source_orchestration.py` owns the parent-held private allowlist, bounded
  process group, `close_fds`/single-passed-receipt-descriptor launch, exact
  state/output/cache roots, live receipt join, and source-orchestration
  evidence set. `replay.py` and `replay_gate.py` consume that same contract in
  a different detached worktree/run namespace. G211 persists the two G240
  evidence-set families and G238 consumes the detached replay boundary.
- Confinement boundary: Landlock is one layer, not the complete authority.
  The parent first binds clean source, recursive gitlinks, the pinned
  interpreter/runtime, the exact command, and private path/port policy. The
  minimal child then verifies its inherited-descriptor set before confinement,
  applies `no_new_privs` and the exact Landlock ruleset, and emits a receipt
  tied by a private one-shot pipe to that actual bounded process. G211/G238 and
  external G243 must subsequently source-replay the public CIDs against the
  private sources. Landlock authenticates allowed filesystem objects and TCP
  destination ports, not peer IP addresses; it does not restrict UDP or
  pathname UNIX sockets, and it cannot revoke descriptors opened before
  confinement. Those residuals are therefore controlled by the minimal
  bootstrap, zero inherited sockets, `close_fds`, the child environment,
  endpoint identity validation, and external negative tests. Any unsupported
  ABI, broader path set, extra descriptor/socket, alternate port, or missing
  layer fails closed.
- Git materialization boundary: Every preparatory Git command uses a canonical
  non-group/world-writable system executable, requires Git 2.40 or newer, and
  runs with an exact environment that discards caller Git/config/loader
  injection. Hooks, fsmonitor, checkout filters, inherited templates, URL
  rewrites, protocol overrides, and network/remote-helper fallbacks fail
  closed. Only the exact already-provisioned local `file` source is enabled
  for a pinned `--checkout --no-fetch` submodule operation; every destination
  child is then revalidated. The production G240 contract separately binds
  its runtime Git executable by raw CID. This is a static malicious
  repository/configuration threat model for a non-root actor: concurrent
  same-user mutation between a preflight and its Git use remains a TOCTOU
  residual controlled operationally by frozen exclusive worktrees.
- Platform boundary: Production confinement and checkout-mode/umask claims
  are Linux/POSIX-specific, and a supported Landlock ABI is mandatory. The
  earlier inspection of the host `landlock.h` constants was only an ABI
  capability check; the header is neither edited nor a build/runtime
  dependency.
- Implementation result: `HSSLEV2405D72` now marks the bounded local
  implementation after 87 source/worktree/detached-replay tests, 21 source
  reconciliation tests, 15 adversarial Git-materialization tests, and four
  independent transport/materialization replays passed. Real production-child
  tests cover the pinned runtime/environment, cache truth, compiler
  source/proof joins, available-SyMAI route provenance, Landlock receipt, and
  detached replay. No operational execution population, endpoint/model
  identity, holdout authorization, or external HSSL-G243 completion is claimed.
- Refinement depth: 2
- Holdout boundary: Implementation uses synthetic identifiers only and cannot read pilot/development or holdout inputs.
- Backlog alignment: HSSL-G240 is now explicitly the implementation-readiness
  prerequisite for G202. HSSL-G243 separately owns external validation of the
  actual G201/G212 namespace and process population, so implementation evidence
  cannot be mistaken for a measured run and no dependency cycle through G202
  remains.

## HSSL-G203 Restore and independently validate the intended Leanstral P2P topology

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G112, HSSL-G239
- Fib priority: 267914296
- Track: benchmark-remediation
- Priority: P0
- Bundle: objective/hssl/leanstral-p2p-topology
- Parallel lane: objective/hssl/leanstral-p2p-topology
- Evidence: HSSLEV2038F96
- Completion authority: external
- Goal: Restore the user-requested P2P model-serving path for the exact shared Leanstral identity and independently verify its complete local advertisement, custom-port, peer-discovery, pubsub, and MCP model-manager topology before the final benchmark source freeze.
- Outputs: any required P2P/model-manager source and lock corrections, focused source-safe tests, and an external source-bound CID receipt for listener, advertisement, peer, rendezvous, pubsub/floodsub, model-manager, and MCP discovery observations
- Validation: perform bounded non-corpus listener, advertisement, peer-dial, rendezvous, pubsub/floodsub, model-manager, and MCP model-list checks without invoking the language model
- Acceptance: The canonical transport lock requests P2P; the service listens on the previously assigned custom port rather than port 8000; every policy-approved active local interface is represented by a dialable advertised multiaddress while wildcard, loopback-only, stale container-only, and unrelated interfaces are rejected; the exact custom port and peer ID agree across listener and advertisement evidence; configured bootstrap and rendezvous peers are nonempty and successfully exercised; pubsub/floodsub participation is observed according to the frozen provider policy; a bounded independent dial succeeds; model-manager and MCP clients discover exactly the same logical `leanstral_local` service and Leanstral model while raw HTTP truthfully retains `llamacpp` transport; no duplicate model server is started; and every public observation is source-bound and content-addressed without secrets.
- Gap task: Diagnose the current disabled P2P lock and single-address/custom-port mismatch, repair the existing service rather than substituting HTTP or starting a duplicate model server, add topology validators, and publish one independent external completion receipt.
- Evidence implementation: Submodule commits `fbaa1f1b` and `1ccaf366` restore the source-side topology contract and add its bounded collector: wildcard listener port 19001, explicit active-interface advertisement policy, canonical bootstrap peers, current py-libp2p rendezvous construction and same-service-peer mounting, bounded probe receipts, truthful disabled pubsub/floodsub claims, strict external-observation decoding, CIDv1 topology receipts, and unambiguous logical-model, HTTP-transport, and P2P identities. Live review then exposed two implementation defects that synthetic topology construction had not covered: Trio rejects `stdout=subprocess.PIPE` in this API, and py-libp2p TCP cannot dial a `/dnsaddr/` address without resolving its TXT descendants. Submodule commits `f631db4c` and `5d969f28` now use Trio's capture API and resolve only same-peer plain-TCP DNSADDR descendants before dialing while retaining the configured DNSADDR identity in public evidence. Focused source-safe topology validation passes 32 tests.
- Diagnostic result: An inference-free live collection at submodule source `5d969f284b0c0b5dbf2091ec0abc2696d6a2a441` passed all four canonical bootstrap dials, same-service rendezvous, an independent client-process dial, and exact direct-model-manager/MCP model-list agreement. It observed wildcard listener `/ip4/0.0.0.0/tcp/19001` and advertised `10.10.0.14`, `10.8.0.99`, and `172.30.4.2` on port 19001 for logical service `leanstral_local`, `llamacpp` transport, and the frozen Leanstral model identity. Its diagnostic receipt CID is `bafkreiacx2qd2ftem6cuyvx2m3eyp7ll4uhk5xs3erxn5cioydxs72wwwy`. This receipt is not final completion evidence because it predates the final outer clean source freeze; the persistent user service also remains on its older reviewed deployment until the new submodule source is separately promoted.
- Refinement depth: 2
- Holdout boundary: This goal uses only service identity and non-inference topology checks; it cannot open pilot/development or holdout inputs.
- Backlog alignment: The earlier HSSL-G112 implementation marker proves attach-only HTTP/model-manager/MCP verification and an optional P2P schema, not the live user-requested P2P topology. The lock and source now request the intended topology, but HSSL-G203 remains operationally incomplete until a fresh external independent topology receipt satisfies its declared completion authority.

## HSSL-G231 Compose all positive source-recomputed gate validators

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G234, HSSL-G235, HSSL-G236, HSSL-G237, HSSL-G238
- Fib priority: 14930352
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/revised-pilot-validators
- Parallel lane: objective/hssl/revised-pilot-validators
- Evidence: HSSLEV2312F74
- Goal: Implement and integrate semantic, causal, safety, paired-efficacy,
  resource, replay, statistical, and Pareto validators into one typed
  fail-closed gate set without trusting self-asserted gate CIDs.
- Outputs: benchmarks/logic_pipeline/positive_gate_bundle.py,
  benchmarks/logic_pipeline/revised_pilot_authorization.py,
  tests/integration/benchmarks/logic_pipeline/test_positive_gate_bundle.py,
  tests/integration/benchmarks/logic_pipeline/test_g231_operational_conformance.py,
  tests/integration/benchmarks/logic_pipeline/test_revised_pilot_authorization.py,
  tests/integration/benchmarks/logic_pipeline/test_revised_pilot_positive_gates.py
- Validation: python -m pytest
  tests/integration/benchmarks/logic_pipeline/test_positive_gate_bundle.py
  tests/integration/benchmarks/logic_pipeline/test_g231_operational_conformance.py
  tests/integration/benchmarks/logic_pipeline/test_revised_pilot_authorization.py
  tests/integration/benchmarks/logic_pipeline/test_revised_pilot_positive_gates.py
  -q
- Acceptance: Source-safe tests prove that every validator source-replays the
  complete HSSL-G200 semantic authority, full HSSL-G211/HSSL-G212 runtime
  evidence, exact HSSL-G220 seal identity, frozen execution identities,
  independent safety and native-kernel authority, paired efficacy and resource
  evidence, and replay/statistical receipts; self-asserted, reduced, stale,
  incomplete, or mismatched evidence fails closed. Tests use only synthetic
  identities and open no protected source or holdout. This goal proves the
  implementation, not the existence or success of an operational gate bundle.
- Gap task: Keep the locally complete composite regression-closed and bind it
  into G202's exact clean-source freeze. HSSL-G242 separately owns external
  application of this validator set to the real G201/G212 population.
- Implementation result: The composite now source-recomputes HSSL-G234 through
  HSSL-G238 and requires both persisted G211 split batches, non-null G240
  runtime-namespace and source-orchestration evidence with private validation
  sources, and G238 detached replay sources. It binds those recomputed
  evidence-set and replay-orchestration CIDs into the positive bundle rather
  than accepting caller-supplied summaries. `HSSLEV2312F74` now marks that
  bounded local implementation after its exact 51-test source-safe composite
  suite and the final G240 trust-chain regressions passed. No operational
  positive bundle exists, and
  `G230RevisedPilotDecision` remains structurally negative-only.
- Refinement depth: 2
- Holdout boundary: Validator implementation and synthetic validation cannot authorize or inspect holdout.
- Backlog alignment: HSSL-G231 is the implementation join and retains every
  validator child edge. HSSL-G242 is the externally governed operational join.
  Completing HSSL-G231 can make G202 freeze-ready but can never assert that a
  measured matrix passed or authorize evaluation.

## HSSL-G202 Freeze the final revision-2 source, run plan, and live capabilities

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G200, HSSL-G203, HSSL-G211, HSSL-G231, HSSL-G239, HSSL-G240
- Fib priority: 165580141
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/revision2-source-capability-freeze
- Evidence: HSSLEV2021E85
- Completion authority: external
- Goal: Create one fresh detached source/run identity after every revision-2 implementation and validator freezes, then independently re-probe the exact live spaCy, SyMAI/router, Hammer, Leanstral, Lean/Lake, cache, scheduler, and native-kernel capabilities before any measured coordinate executes.
- Outputs: an external source-reconciled baseline, recursive-gitlink receipt, immutable run plan, capability inventory/freeze, component smoke receipts, resource policy, process/cache namespaces, and independent validation receipt
- Validation: validate the clean detached source and recursive gitlinks; execute bounded non-corpus component smokes; source-recompute the complete freeze without reading any benchmark source or holdout
- Acceptance: One clean detached outer commit and every recursive gitlink match the reviewed source; the final protocol, registry, prompts, gate schemas, case-loader boundaries, routes, thresholds, model identities, cache/resource policy, and exact G201/G212 coordinate plan are frozen; requested equals effective for all eight capabilities; the exact fresh HSSL-G203 P2P topology receipt is source-revalidated; raw Leanstral service metadata truthfully distinguishes `llamacpp` transport from the logical `leanstral_local` route; no HTTP-only substitution, fallback, duplicate service, secret, dirty source, attached worktree, stale revision-1 receipt, or self-asserted health flag enters the freeze; all namespaces are fresh and disjoint; and no benchmark source or holdout is opened.
- Gap task: After every implementation lane passes, commit a clean source tree, prepare a fresh detached recursive worktree, execute the full source-safe capability reprobe, and freeze one immutable run plan for G201/G212/G220/G232/G241.
- Evidence implementation: The G202 constructor now derives the exact G201 semantic preflight and G210 rescue input plans only from source targets, cases, manifests, and canonical `AblationPlan` values. It binds the preregistered G240 executor-contract policy before execution. Runtime identity replay binds adapter ID/version, canonical adapter module, complete observed source provenance, environment SHA/CID, and lane/split/case/cache/variant/stage coordinates. No G202 preflight field is derived from a `CaseResult` or post-run outcome.
- Implementation result: Source-safe synthetic tests cover the repaired preflight/provenance boundary and reject result-derived, adapter-rebased, environment-rebased, or coordinate-rebased identities. This is implementation evidence only: no valid HSSL-G202 external completion receipt, final clean detached freeze, or live capability/P2P receipt exists.
- Refinement depth: 2
- Holdout boundary: G202 uses only code, identities, and non-corpus smokes. It cannot inspect pilot/development or holdout sources.
- Backlog alignment: Prior HSSL-G113/HSSL-G120 receipts bind old source commit `3e053f6edece026fef48c153aa5c4d62a50da3d2` and revision 1; they are diagnostic inputs only and cannot satisfy this goal. Any implementation change after G202 invalidates the entire run.

## HSSL-G243 Externally validate the operational source-execution population

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G201, HSSL-G202, HSSL-G212, HSSL-G239, HSSL-G240
- Fib priority: 1836311903
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/operational-runtime-namespace-evidence
- Parallel lane: objective/hssl/operational-runtime-namespace-evidence
- Evidence: HSSLEV2437B58
- Completion authority: external
- Goal: Independently source-recompute the actual G201/G212 process,
  environment, confinement, cache, state, output, and detached-replay
  population produced by the locally integrated HSSL-G240 executor under the
  exact HSSL-G202 freeze.
- Outputs: an external complete-coordinate population index; source-bound
  runtime-namespace, source-orchestration, confinement, cache-behavior, process
  lifecycle, and detached-replay receipt CIDs; and one typed G239-governed
  completion receipt
- Validation: In a fresh detached recursive worktree and isolated namespace,
  replay every successful coordinate and the preregistered failure sample from
  canonical receipts without invoking a front end, model, compiler, solver, or
  kernel a second time except where the frozen G238 detached-replay protocol
  explicitly requires it.
- Acceptance: Every G201/G212 coordinate required by the G202 plan is present
  exactly once and source-replays to the same clean commit, recursive gitlinks,
  environment and toolchain CIDs, namespace policy, case/variant/split/cache
  coordinate, actual prime/hit cache semantics, process-group lifecycle, and
  canonical runtime bytes. The independent validator observes mandatory
  Landlock enforcement, only the frozen local service port is connectable,
  where that production-child rule means outbound TCP destination port 8080
  and does not grant, probe, or validate the separate G203 P2P listener on
  port 19001; protected paths are outside the filesystem allowlist, every
  subprocess is
  reaped, and no ambient environment, unbound Git executable, shared mutable
  SyMAI prefix, reduced receipt, caller-supplied replay expectation, or
  path-leaking public evidence is accepted. Missing, duplicated, stale,
  rebased, unconstrained, or implementation-only evidence fails closed.
- Gap task: Run this external population validation only after HSSL-G201 and
  HSSL-G212 finish under the final G202 freeze. Synthetic G240 tests and the
  HSSL-G240 implementation marker cannot satisfy it.
- Refinement depth: 3
- Holdout boundary: This goal validates pilot/development identities and
  runtime receipts only. It cannot load replacement-holdout source, labels, or
  results and cannot authorize holdout access or production.
- Backlog alignment: HSSL-G243 is the operational half split from HSSL-G240.
  It removes the former G202 dependency cycle while retaining external
  completion authority for every claim about an actual measured population.

## HSSL-G242 Externally apply the positive validators to the measured matrix

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G201, HSSL-G202, HSSL-G212, HSSL-G220, HSSL-G231, HSSL-G239, HSSL-G243
- Fib priority: 1134903170
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/operational-positive-gate-bundle
- Parallel lane: objective/hssl/operational-positive-gate-bundle
- Evidence: HSSLEV2424C63
- Completion authority: external
- Goal: Apply the locally integrated HSSL-G231 validator set to the exact
  externally validated HSSL-G201/G212/G220/G243 source graph and publish a
  source-recomputed positive-gate bundle or an explicit negative result without
  re-invoking any measured component.
- Outputs: canonical source indexes, independently recomputed semantic,
  causal, safety, quality, efficacy, reliability, routing, cost, resource,
  statistical, Pareto, and replay gate receipts, the exact complete positive
  bundle CID when all gates pass, and one typed G239-governed completion receipt
- Validation: Reconstruct the HSSL-G231 bundle from canonical source records in
  a fresh detached recursive worktree; compare the result with the frozen
  G202 plan, HSSL-G220 seal, and HSSL-G243 population receipt; invoke no
  benchmark producer, backend, model, compiler, solver, or native kernel.
- Acceptance: Every declared arm and coordinate is terminal and source-bound;
  semantic and causal denominators are complete and non-vacuous; invalid
  controls have zero kernel-verified false positives; semantic quality,
  efficacy, reliability, routing, cost, resources, paired statistics, Pareto,
  and replay evidence are non-null; producer, meter, reviewer, and validator
  authorities remain independent; and all derived CIDs recompute from the exact
  G202/G201/G212/G220/G243 source graph. Any missing, stale, reduced,
  self-asserted, implementation-only, source-rebased, or authority-overlapping
  evidence yields an explicit negative bundle and no positive CID.
- Gap task: Execute this external source join only after HSSL-G243 validates
  the complete measured population. Local HSSL-G231 tests cannot satisfy this
  goal.
- Refinement depth: 3
- Authorization boundary: A positive HSSL-G242 bundle is evidence for HSSL-G232
  only. It does not select candidates, release holdout custody, change
  production routing, or authorize promotion.
- Holdout boundary: The validator may bind only the public opaque HSSL-G220
  seal identity. It cannot open the replacement holdout.
- Backlog alignment: HSSL-G242 is the operational half split from HSSL-G231.
  It preserves external authority for measured claims while allowing the
  implementation-only HSSL-G231 prerequisite to complete before G202.

## HSSL-G232 Join the revised pilot evidence and freeze exact replacement-holdout authorization

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G201, HSSL-G212, HSSL-G220, HSSL-G202, HSSL-G242, HSSL-G243
- Fib priority: 24157817
- Track: benchmark-reassessment-v2
- Priority: P0
- Bundle: objective/hssl/revised-pilot-execution
- Parallel lane: objective/hssl/revised-pilot-execution
- Evidence: HSSLEV2329A65
- Completion authority: external
- Goal: Join and independently validate the already executed G201 semantic and G212 causal/resource submatrices under the identical G202 run plan, then freeze either an exact nonempty eligible shortlist proposal bound to the HSSL-G220 replacement seal or an empty shortlist that authorizes nothing.
- Outputs: an external complete matrix index, joined semantic/proof/cost/resource/statistics gate bundle, pilot-shortlist decision, proposed G232 replacement-holdout authorization, and dated validation snapshot
- Validation: validate the complete source-bound pilot artifact with the HSSL-G231 validators in the isolated run namespace
- Acceptance: The exact G202 commit, gitlinks, run plan, capability freeze, namespaces, protocol, registry, prompts, backend/model identities, cache/resource policy, semantic projection, causal kernel policy, complete G201/G212 receipt graphs, and HSSL-G220 seal all agree; no backend, producer, solver, model, or kernel is re-invoked during the join; every preregistered coordinate is terminal and source-bound; calibration is complete and non-vacuous; external verification exposure is identical; causal rescue and all denominators are complete; invalid controls have zero kernel-verified false positives; efficacy, quality, cost, reliability, routing, replay, and Pareto evidence are non-null; and the deterministic source-derived eligible shortlist contains one to four candidates passing every absolute, paired, safety, resource, and replayability gate before a content-addressed `G232ReplacementHoldoutAuthorization` proposal is created for the exact replacement seal. Any failure emits an empty shortlist with no authorization digest. The proposal is evidence for HSSL-G241 and is not by itself a custodian-release authority.
- Gap task: Join and source-recompute the frozen G201/G212/G220 evidence after all three complete, publish independent gate receipts, and validate the exact pilot decision without re-execution or holdout access.
- Refinement depth: 2
- Authorization boundary: This goal may propose only the exact source-recomputed shortlist and HSSL-G220 manifest. HSSL-G241 must independently source-recompute and externally authorize the custodian handoff; neither goal authorizes production promotion.
- Holdout boundary: HSSL-G232 cannot open holdout or release access by itself. Revision-1 HSSL-G150 and its retired holdout remain ineligible.
- Backlog alignment: HSSL-G232 is the pilot evidence join from the final G202
  freeze, complete semantic/causal execution, independent replacement custody,
  externally validated runtime population, and externally recomputed positive
  bundle. HSSL-G241 is the sole release join to any future revision-2 holdout
  executor. Generated metadata must preserve all six HSSL-G232 parent edges and
  must never schedule a second pilot/development run.

## HSSL-G241 Enforce the externally governed G232-to-custodian handoff

- Status: active
- Goal completion schema version: 1
- Parent: HSSL-G201, HSSL-G202, HSSL-G211, HSSL-G212, HSSL-G220, HSSL-G231, HSSL-G232, HSSL-G239, HSSL-G242, HSSL-G243
- Fib priority: 701408733
- Track: benchmark-holdout-revision
- Priority: P0
- Bundle: objective/hssl/custodian-release-authority
- Evidence: G241ExternallyGovernedCustodianReleaseReceiptV1
- Completion authority: external
- Goal: Add the sole operational adapter that source-recomputes the positive HSSL-G231 bundle and the exact HSSL-G202/G201/G211/G212/G220/G232 identity chain under HSSL-G239 external governance before an independent custodian may release the replacement holdout to an executor.
- Outputs: a typed identity-only G241 custodian-release request and receipt, an exact source index for the G231/G232 decision chain, an independently controlled append-only handoff ledger, focused source-safe validator tests, and a documented external receipt schema
- Validation: In a clean detached source tree, source-recompute the complete identity graph and exercise positive and negative synthetic handoff cases without loading a benchmark case, corpus, manifest body, proof obligation, model output, or holdout byte
- Acceptance: The adapter reparses the complete positive HSSL-G231 bundle from its canonical source records; requires the exact HSSL-G202 clean commit, tree, recursive gitlinks, run plan, capability/environment freeze, and namespace policy; requires the exact complete HSSL-G201 semantic, HSSL-G211 persisted-runtime, and HSSL-G212 causal/resource receipt graphs; binds the exact HSSL-G220 seal and access-ledger authority; and validates a current HSSL-G239-governed external-completion receipt whose parent ledger, artifact CIDs, producer identity, and independent validator identity cover this same chain. The proposed HSSL-G232 candidate set must equal the deterministic nonempty shortlist derived by source replay, with A0 added only as the paired baseline; a cardinality of one to four is necessary but never sufficient. A constructor supplied only arbitrary canonical CIDs, booleans, or one to four caller-chosen arm IDs cannot mint a release. Missing, stale, synthetic, reduced, duplicated, source-rebased, authority-overlapping, self-signed, marker-only, or internally generated evidence produces no release receipt. The decision producer, external validator, custodian, and holdout executor identities are pairwise distinct, and the handoff records zero holdout reads, writes, schedules, backend calls, and result coordinates.
- Gap task: Complete independent review and integration of the source-safe adapter, then obtain a valid external G239-governed receipt and custodian handoff only after every upstream operational goal passes.
- Evidence implementation: `benchmarks/logic_pipeline/custodian_release.py` implements the identity-only source replay, exact deterministic G232 proposal reconstruction, complete G202/G201/G211/G212/G220/G231 parent and artifact joins, dedicated G239 external-authority projection, independently pinned custodian trust root, pairwise authority separation, zero-activity assertion, and private append-only handoff ledger. The only operational receipt constructor is `authorize_g241_custodian_release_v1`.
- Implementation result: The source-safe G241 gate is implemented and rejects arbitrary shortlist CIDs, incomplete/rebased source graphs, authority overlap, synthetic self-authorization, and premature holdout activity. There is no G241 implementation marker, external completion or release receipt, custodian handoff, or holdout access.
- Refinement depth: 2
- Authorization boundary: Only a valid G241 receipt may release the exact HSSL-G220 seal for paired A0 plus the exact source-derived HSSL-G232 shortlist. It grants no discretion to add, remove, reorder, or substitute arms and does not authorize production.
- Holdout boundary: HSSL-G241 validates and records the handoff but cannot load or execute holdout. Any nonzero holdout activity before the custodian validates the receipt permanently invalidates the seal instead of satisfying this goal.
- Synthetic boundary: Synthetic tests may prove schema rejection and source replay only; they cannot create an operational receipt or satisfy external completion authority.
- Backlog alignment: HSSL-G241 is deliberately downstream of HSSL-G232 and
  explicitly retains every source, operational-gate, runtime-population, and
  governance identity that the custodian must verify. Generated supervisor
  metadata must keep all ten parent edges, must not infer completion from
  constructing `G232ReplacementHoldoutAuthorization`, and must never treat an
  HSSL-G239 implementation marker as external authorization.
