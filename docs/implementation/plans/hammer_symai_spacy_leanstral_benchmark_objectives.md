# Hammer, SyMAI, spaCy, and Leanstral Benchmark Objective Heap

This is machine-ingestible planning state for
`ipfs_accelerate_py.agent_supervisor.objective_daemon`. Goal completion requires
the named evidence receipt and the validation command; model confidence alone
is never completion evidence.

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
