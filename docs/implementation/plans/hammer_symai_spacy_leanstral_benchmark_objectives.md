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
