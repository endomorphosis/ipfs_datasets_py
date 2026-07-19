# ITP Hammer Integration Taskboard

Status: Planned
Date: 2026-07-19
Scope: A kernel-checked hammer pipeline for `ipfs_datasets_py/logic` that selects premises, translates supported goals to TPTP or SMT-LIB, runs a bounded solver portfolio, and reconstructs a proof in the originating Interactive Theorem Prover (ITP).

## Operating Rules

This board is intentionally narrower than a claim that all prover logics are interchangeable. Lean, Coq/Rocq, and Isabelle/HOL each require a native frontend and a native reconstruction/checking adapter. A solver `sat`, `unsat`, or `proved` response is an untrusted candidate, never a verified theorem. A result may be marked `verified` only after the target ITP kernel accepts the reconstructed proof under a pinned environment.

The first implementation target is a deterministic, auditable interface around existing `ipfs_datasets_py` capabilities: optional prover installation, TPTP output, SMT-LIB output, and external Vampire/E/Z3/CVC5 lanes. Unsupported higher-order, dependent-type, polymorphic, or lambda terms must produce an explicit `unsupported_translation` result rather than silently erasing semantics. All external executable paths, timeouts, CPU and memory budgets, and network access must be policy-controlled.

LLMs may propose premise rankings or a decomposition plan only when an operator enables that capability. They must not supply an accepted proof, suppress an unsupported translation, or turn an unverified external proof into a `verified` result.

## Supervisor Invocation

Use the `ipfs_accelerate_py` implementation daemon with this board and prefix:

```bash
PYTHONPATH=/path/to/ipfs_accelerate_py:/path/to/ipfs_datasets_py \
python -m ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon \
  --todo-path docs/logic/itp_hammer_taskboard.todo.md \
  --task-prefix '## HAMMER-' \
  --state-dir data/itp_hammer_supervisor/state \
  --state-prefix itp_hammer --implement
```

## HAMMER-001 Define the hammer trust contract and result schema

- Status: completed
- Priority: P0
- Track: architecture
- Depends on:
- Outputs: docs/logic/itp_hammer_contract.md, ipfs_datasets_py/logic/hammers/models.py, tests/unit_tests/logic/hammers/test_models.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_models.py -q
- Acceptance: Define versioned request, premise, translation, solver-attempt, proof-candidate, reconstruction, environment-lock, and final-result records. Enforce the result states `verified`, `candidate`, `counterexample`, `unknown`, `timeout`, `unsupported_translation`, `unavailable`, and `policy_denied`; only a successful kernel check may create `verified`.

## HAMMER-002 Inventory existing logic, ITP, ATP, and SMT capabilities

- Status: completed
- Priority: P0
- Track: discovery
- Depends on:
- Outputs: docs/logic/itp_hammer_capability_inventory.md, scripts/ops/logic/probe_itp_hammer_environment.py, data/logic/itp_hammer/environment.json, tests/unit_tests/logic/hammers/test_environment_probe.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_environment_probe.py -q; PYTHONPATH=. python scripts/ops/logic/probe_itp_hammer_environment.py --out data/logic/itp_hammer/environment.json
- Acceptance: Discover and version existing Lean, Coq/Rocq, Isabelle, Z3, CVC5, Vampire, E, TPTP, SMT-LIB, TDFOL, CEC, and prover-installer surfaces without installing or invoking a solver by default. Record executable paths, native proof-trace support, parser support, and explicit unavailable states.

## HAMMER-003 Build a content-addressed premise corpus and theorem manifest

- Status: waiting
- Priority: P0
- Track: data
- Depends on: HAMMER-001, HAMMER-002
- Outputs: ipfs_datasets_py/logic/hammers/corpus.py, docs/logic/itp_hammer_corpus.md, tests/unit_tests/logic/hammers/test_corpus.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_corpus.py -q
- Acceptance: Ingest only declared theorem corpora into a versioned manifest with theorem identity, source ITP, imports, normalized statement digest, license metadata, and CID or deterministic content digest. Reject duplicate identities with different statements and retain the corpus revision in every hammer result.

## HAMMER-004 Implement deterministic premise selection baselines

- Status: waiting
- Priority: P0
- Track: retrieval
- Depends on: HAMMER-003
- Outputs: ipfs_datasets_py/logic/hammers/premise_selection.py, docs/logic/itp_hammer_premise_selection.md, tests/unit_tests/logic/hammers/test_premise_selection.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_premise_selection.py -q
- Acceptance: Rank premises deterministically from goal symbols, types, imports, and dependency graph features. Emit selected IDs, scores, corpus revision, cutoff, and excluded candidates; enforce bounded `top_k` and stable ordering for identical input.

## HAMMER-005 Add an optional learned premise selector behind evaluation gates

- Status: waiting
- Priority: P1
- Track: retrieval
- Depends on: HAMMER-004
- Outputs: ipfs_datasets_py/logic/hammers/learned_selector.py, docs/logic/itp_hammer_learned_selection.md, benchmarks/bench_itp_hammer_premise_selection.py, tests/unit_tests/logic/hammers/test_learned_selector.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_learned_selector.py -q; PYTHONPATH=. python benchmarks/bench_itp_hammer_premise_selection.py --fixture tests/fixtures/logic/hammers --out data/logic/itp_hammer/premise-selection-benchmark.json
- Acceptance: Keep the deterministic baseline as the default. Permit a learned or graph-based selector only with a pinned model digest, held-out recall/latency comparison, reproducible feature extraction, opt-in configuration, and a fallback to the baseline when the model is missing or fails.

## HAMMER-006 Create native ITP frontend adapters and goal snapshots

- Status: waiting
- Priority: P0
- Track: integration
- Depends on: HAMMER-001, HAMMER-002
- Outputs: ipfs_datasets_py/logic/hammers/frontends/lean.py, ipfs_datasets_py/logic/hammers/frontends/coq.py, ipfs_datasets_py/logic/hammers/frontends/isabelle.py, tests/integration/logic/hammers/test_itp_frontends.py
- Validation: PYTHONPATH=. python -m pytest tests/integration/logic/hammers/test_itp_frontends.py -q
- Acceptance: Define a common adapter protocol that captures the exact goal, local hypotheses, imports, universe/type context, source position, target ITP version, and native command needed for reconstruction. Each unavailable frontend returns structured capability evidence; no adapter fabricates a native goal from plain text.

## HAMMER-007 Implement typed translation to TPTP and SMT-LIB

- Status: waiting
- Priority: P0
- Track: translation
- Depends on: HAMMER-001, HAMMER-004, HAMMER-006
- Outputs: ipfs_datasets_py/logic/hammers/translation.py, ipfs_datasets_py/logic/hammers/tptp.py, ipfs_datasets_py/logic/hammers/smtlib.py, tests/unit_tests/logic/hammers/test_translation.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_translation.py -q
- Acceptance: Lower only supported fragments through explicit monomorphization, lambda lifting or elimination, and type encodings. Persist a translation map and obligations for each transformed construct. Round-trip tests and negative fixtures must prove that unsupported dependent, higher-order, or opaque constructs fail closed.

## HAMMER-008 Add policy-controlled parallel ATP and SMT portfolio execution

- Status: waiting
- Priority: P0
- Track: execution
- Depends on: HAMMER-002, HAMMER-007
- Outputs: ipfs_datasets_py/logic/hammers/portfolio.py, ipfs_datasets_py/logic/hammers/policy.py, tests/unit_tests/logic/hammers/test_portfolio.py, tests/integration/logic/hammers/test_solver_portfolio.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_portfolio.py tests/integration/logic/hammers/test_solver_portfolio.py -q
- Acceptance: Execute an allowlisted Z3/CVC5/Vampire/E portfolio with independent time, memory, process-count, and cancellation budgets. Capture command version, input digest, stdout/stderr digest, exit status, timeout, and solver trace. Never interpolate user content into a shell command or expose a solver result as verified.

## HAMMER-009 Normalize proof traces and counterexample evidence

- Status: waiting
- Priority: P0
- Track: provenance
- Depends on: HAMMER-008
- Outputs: ipfs_datasets_py/logic/hammers/provenance.py, docs/logic/itp_hammer_provenance.md, tests/unit_tests/logic/hammers/test_provenance.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_provenance.py -q
- Acceptance: Normalize solver proofs, unsat cores, models, and counterexamples into content-addressed candidate evidence. Preserve premise IDs and translation map references. A malformed, absent, or unsupported trace results in `candidate` or `unknown`, never `verified`.

## HAMMER-010 Implement native proof reconstruction and kernel verification

- Status: waiting
- Priority: P0
- Track: trust
- Depends on: HAMMER-006, HAMMER-009
- Outputs: ipfs_datasets_py/logic/hammers/reconstruction.py, ipfs_datasets_py/logic/hammers/reconstructors/lean.py, ipfs_datasets_py/logic/hammers/reconstructors/coq.py, ipfs_datasets_py/logic/hammers/reconstructors/isabelle.py, tests/integration/logic/hammers/test_reconstruction.py
- Validation: PYTHONPATH=. python -m pytest tests/integration/logic/hammers/test_reconstruction.py -q
- Acceptance: Reconstruct native tactic or proof terms from candidate evidence and invoke the target kernel in a pinned environment. Store the checked source, kernel stdout/stderr, exit status, and digest. Confirm that deliberately corrupted traces and theorem statements cannot produce `verified`.

## HAMMER-011 Add native-automation and decomposition fallbacks

- Status: waiting
- Priority: P1
- Track: recovery
- Depends on: HAMMER-010
- Outputs: ipfs_datasets_py/logic/hammers/fallbacks.py, docs/logic/itp_hammer_failure_policy.md, tests/unit_tests/logic/hammers/test_fallbacks.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_fallbacks.py -q
- Acceptance: On translation, search, or reconstruction failure, try an explicitly enabled native tactic such as Lean automation, then return a bounded subgoal decomposition plan. Any LLM-assisted plan is redacted, reviewed, and marked untrusted until each resulting native subproof passes the kernel.

## HAMMER-012 Persist replayable hammer receipts through IPFS-aware storage

- Status: waiting
- Priority: P1
- Track: storage
- Depends on: HAMMER-003, HAMMER-009, HAMMER-010
- Outputs: ipfs_datasets_py/logic/hammers/receipts.py, docs/logic/itp_hammer_receipts.md, tests/unit_tests/logic/hammers/test_receipts.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/hammers/test_receipts.py -q
- Acceptance: Persist canonical request, selected premises, translation artifacts, solver candidates, reconstruction sources, environment lock, and verification outcome with content digests or CIDs. Support local-disk fallback and redact private theorem sources, credentials, and raw prompts from publishable receipts.

## HAMMER-013 Expose governed MCP and CLI hammer operations

- Status: waiting
- Priority: P1
- Track: interfaces
- Depends on: HAMMER-008, HAMMER-010, HAMMER-012
- Outputs: ipfs_datasets_py/mcp_server/tools/logic_hammer.py, scripts/cli/logic_cli.py, docs/logic/itp_hammer_mcp_contract.md, tests/integration/logic/hammers/test_mcp_hammer_tools.py
- Validation: PYTHONPATH=. python -m pytest tests/integration/logic/hammers/test_mcp_hammer_tools.py -q
- Acceptance: Provide inspect, select-premises, translate, run-candidate, reconstruct, retrieve-receipt, and capability-status operations. Govern execution with explicit policy, confirmation for native process launch, correlation IDs, structured unavailable states, and no claim that a candidate proof is verified before kernel confirmation.

## HAMMER-014 Build end-to-end golden corpus and adversarial test suites

- Status: waiting
- Priority: P0
- Track: quality
- Depends on: HAMMER-004, HAMMER-007, HAMMER-008, HAMMER-010, HAMMER-011, HAMMER-012
- Outputs: tests/fixtures/logic/hammers, tests/integration/logic/hammers/test_end_to_end_hammer.py, tests/integration/logic/hammers/test_adversarial_hammer.py, data/logic/itp_hammer/golden-report.json
- Validation: PYTHONPATH=. python -m pytest tests/integration/logic/hammers/test_end_to_end_hammer.py tests/integration/logic/hammers/test_adversarial_hammer.py -q
- Acceptance: Cover verified, candidate-only, counterexample, timeout, unavailable solver, unsupported translation, malformed proof trace, corrupted receipt, premise-poisoning, and cancellation cases. Verify stable corpus and receipt digests, and require every claimed verified result to have an actual native kernel acceptance record.

## HAMMER-015 Publish benchmarks, documentation, and release gate

- Status: waiting
- Priority: P1
- Track: release
- Depends on: HAMMER-005, HAMMER-013, HAMMER-014
- Outputs: docs/logic/itp_hammer_user_guide.md, docs/logic/itp_hammer_security_model.md, benchmarks/bench_itp_hammer.py, scripts/ops/logic/release_itp_hammer_gate.py, data/logic/itp_hammer/release-evidence.json
- Validation: PYTHONPATH=. python benchmarks/bench_itp_hammer.py --fixture tests/fixtures/logic/hammers --out data/logic/itp_hammer/benchmark.json; PYTHONPATH=. python scripts/ops/logic/release_itp_hammer_gate.py --evidence data/logic/itp_hammer/release-evidence.json
- Acceptance: Publish supported ITP/solver fragments, benchmark methodology, recall/latency metrics, resource defaults, reproducibility requirements, privacy policy, and limitations. The release gate must fail closed for missing corpus/environment locks, absent kernel proof, stale receipts, or any verified result without kernel acceptance evidence.
