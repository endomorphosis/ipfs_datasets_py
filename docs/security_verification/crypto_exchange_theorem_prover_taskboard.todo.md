# Crypto Exchange Theorem-Prover Security Plan And Taskboard

Status: In Progress
Date: 2026-07-08
Scope: `ipfs_datasets_py/logic/security_models/crypto_exchange`, blockchain wallet and cryptocurrency exchange security verification, theorem-prover execution, disproof testing, runtime evidence, proof-consumer receipts, and the Xaman XRPL wallet corpus.

## Current Review Findings

The reviewed checkout repeatedly lost the `crypto_exchange` source tree and this taskboard after supervisor workers completed. `PORTAL-CXTP-056` recovered source and artifacts from durable commit `5a9ce484a`; `PORTAL-CXTP-057` added a retention baseline; `PORTAL-CXTP-058` added solver/environment probing and found this host blocked for required TypeScript compiler (`tsc`) coverage, with optional prover gaps for Apalache, Tamarin, ProVerif, Lean, and Coq.

The target external corpus is `https://github.com/XRPL-Labs/Xaman-App` pinned to commit `942f43876265a7af44f233288ad2b1d00841d5fa`. The plan treats that corpus as a wallet test target, not as a substitute for deployed production wallet or exchange evidence.

## Security Decision Policy

This workflow can support a "secure under stated assumptions" decision only when every blocking and high-risk claim is modeled, proved by the required prover portfolio, attacked by mutation and counterexample search, bound to reviewed source evidence, bound to a current environment profile, and consumed through valid proof receipts. `DISPROVED`, `UNKNOWN`, `NOT_MODELED`, missing solvers, stale evidence, unreviewed facts, unsupported theories, absent production sources, and missing runtime traces are non-secure outcomes.

The theorem provers prove or disprove formal models. They do not prove the real wallet, exchange, mobile OS, backend, custody hardware, biometric subsystem, network, XRPL consensus, or deployment process secure unless those assumptions are explicitly modeled, evidenced, fresh, and reviewed.

## Proof Portfolio

1. Restore and stabilize source, taskboard, and artifact integrity before any model is trusted.
2. Pin the Xaman corpus at an exact commit, record license/security disclosure files, dependency lockfiles, sparse paths, and file digests.
3. Extract wallet, payload, XRPL transaction, custody, API, policy, and runtime facts into a reviewed `SecurityModelIR`.
4. Encode safety invariants to SMT-LIB and run Z3 plus CVC5 differential checks.
5. Encode temporal signing and broadcast workflows to TLA+/Apalache.
6. Encode payload, session, and secret-flow protocols to Tamarin or ProVerif.
7. Encode proof-consumer and receipt acceptance invariants to Lean or Coq.
8. Run mutation and disproof suites that invert claims, remove preconditions, stale evidence, downgrade solvers, and inject replay/network/custody counterexamples.
9. Ingest runtime and e2e traces, then check trace conformance against the formal model.
10. Produce an assurance packet that lists proved claims, disproved claims, unknowns, assumptions, evidence, solver versions, corpus commit, environment profile, and release decision.

## Agent Supervisor Tasklist

The following tasks are formatted for the `ipfs_accelerate_py` agent supervisor. Each task uses the default `## PORTAL-` header prefix and machine-readable `- Key: value` metadata.

## PORTAL-CXTP-056 Recover crypto_exchange source and verification artifact tree

- Status: completed
- Completion: manual
- Priority: P0
- Track: ops
- Depends on:
- Outputs: docs/security_verification/crypto_exchange_recovery_report.md, security_ir_artifacts/recovery/crypto-exchange-source-audit.json, scripts/ops/security_verification/audit_crypto_exchange_source_tree.py, tests/logic/security_models/crypto_exchange/test_crypto_exchange_source_tree_recovery.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_crypto_exchange_source_tree_recovery.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/audit_crypto_exchange_source_tree.py --out security_ir_artifacts/recovery/crypto-exchange-source-audit.json
- Acceptance: Detect and document source-empty crypto_exchange trees, restore required package files and tests from durable sources where available, fail closed if only bytecode is available, and emit a machine-readable audit that blocks proof acceptance until source files and expected artifacts exist.

## PORTAL-CXTP-057 Protect theorem-prover taskboard and artifact retention

- Status: completed
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-056
- Outputs: docs/security_verification/taskboard_artifact_retention_policy.md, scripts/ops/security_verification/check_crypto_exchange_artifact_retention.py, security_ir_artifacts/recovery/artifact-retention-baseline.json, tests/logic/security_models/crypto_exchange/test_crypto_exchange_artifact_retention.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_crypto_exchange_artifact_retention.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/check_crypto_exchange_artifact_retention.py --baseline security_ir_artifacts/recovery/artifact-retention-baseline.json
- Acceptance: Fail closed when the taskboard, plan, source files, Xaman manifests, model facts, tests, solver artifacts, implementation logs, or assurance packets disappear, and document the restoration path for the agent supervisor.

## PORTAL-CXTP-058 Build solver dependency bootstrap and environment probe

- Status: completed
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-056
- Outputs: docs/security_verification/solver_dependency_bootstrap.md, scripts/ops/security_verification/probe_theorem_prover_environment.py, security_ir_artifacts/environment/solver-dependency-probe.json, tests/logic/security_models/crypto_exchange/test_solver_dependency_probe.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_solver_dependency_probe.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_theorem_prover_environment.py --out security_ir_artifacts/environment/solver-dependency-probe.json
- Acceptance: Probe Python, Node, npm, TypeScript, Z3, CVC5, Apalache, Tamarin, ProVerif, Lean, Coq, OS, CPU, and required env vars; mark missing required solvers as blocking evidence and optional solvers as explicit capability gaps.

## PORTAL-CXTP-088 Stabilize recovered tree across supervisor commit cleanup

- Status: completed
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-056, PORTAL-CXTP-057, PORTAL-CXTP-058
- Outputs: docs/security_verification/supervisor_recovery_stability_runbook.md, scripts/ops/security_verification/restore_crypto_exchange_security_tree.py, security_ir_artifacts/recovery/supervisor-stability-report.json, tests/logic/security_models/crypto_exchange/test_supervisor_recovery_stability.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_supervisor_recovery_stability.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/restore_crypto_exchange_security_tree.py --verify-only --report security_ir_artifacts/recovery/supervisor-stability-report.json
- Acceptance: Make taskboard and source-tree disappearance self-healing after supervisor workers commit or clean untracked outputs; verify source files, taskboard, Xaman artifacts, retention baseline, and solver probe are present before any downstream task can run; fail closed with restoration instructions if durable recovery is unavailable.

## PORTAL-CXTP-089 Remediate required TypeScript compiler dependency

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_typescript_dependency_remediation.py -q; PATH="$PWD/security_ir_artifacts/environment/typescript_toolchain/node_modules/.bin:$PATH" PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_typescript_schema_compiles.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/provision_required_typescript_toolchain.py --probe security_ir_artifacts/environment/solver-dependency-probe.json --out security_ir_artifacts/environment/typescript-remediation-report.json
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-088
- Outputs: docs/security_verification/typescript_solver_dependency_remediation.md, scripts/ops/security_verification/provision_required_typescript_toolchain.py, security_ir_artifacts/environment/typescript-remediation-report.json, tests/logic/security_models/crypto_exchange/test_typescript_dependency_remediation.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_typescript_dependency_remediation.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/provision_required_typescript_toolchain.py --probe security_ir_artifacts/environment/solver-dependency-probe.json --out security_ir_artifacts/environment/typescript-remediation-report.json
- Acceptance: Remove the required `tsc` blocker found by PORTAL-CXTP-058 using a reproducible local or repo-scoped TypeScript compiler path, refresh solver dependency evidence, and keep proof acceptance blocked if TypeScript remains unavailable.

## PORTAL-CXTP-059 Freeze proof-boundary and security decision policy

- Status: completed
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-056, PORTAL-CXTP-088
- Outputs: docs/security_verification/production_release_decision_policy.md, security_ir_artifacts/policies/security-decision-policy.json, tests/logic/security_models/crypto_exchange/test_release_decision_policy.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_release_decision_policy.py -q
- Acceptance: Define prove, disprove, unknown, not-modeled, stale-evidence, missing-solver, and blocked-production outcomes, and require all release consumers to treat non-proved blocking claims as non-secure.

## PORTAL-CXTP-060 Acquire and pin Xaman App corpus

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_corpus_manifest.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/fetch_xaman_corpus.py --repo https://github.com/XRPL-Labs/Xaman-App --ref 942f43876265a7af44f233288ad2b1d00841d5fa --out security_ir_artifacts/corpora/xaman-app/source-manifest.json
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-057, PORTAL-CXTP-059
- Outputs: docs/security_verification/xaman_corpus_profile.md, security_ir_artifacts/corpora/xaman-app/source-manifest.json, scripts/ops/security_verification/fetch_xaman_corpus.py, tests/logic/security_models/crypto_exchange/test_xaman_corpus_manifest.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_corpus_manifest.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/fetch_xaman_corpus.py --repo https://github.com/XRPL-Labs/Xaman-App --ref 942f43876265a7af44f233288ad2b1d00841d5fa --out security_ir_artifacts/corpora/xaman-app/source-manifest.json
- Acceptance: Fetch or reference the Xaman-App corpus at the exact pinned commit, record source URL, commit SHA, sparse checkout paths, file digests, dependency lockfiles, license and security-disclosure files, and fail closed if the corpus cannot be reproduced.

## PORTAL-CXTP-061 Build Xaman dependency and build-environment probe

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_environment_probe.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_xaman_environment.py --corpus-manifest security_ir_artifacts/corpora/xaman-app/source-manifest.json --out security_ir_artifacts/corpora/xaman-app/environment-probe.json
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-060, PORTAL-CXTP-089
- Outputs: docs/security_verification/xaman_environment_assumptions.md, scripts/ops/security_verification/probe_xaman_environment.py, security_ir_artifacts/corpora/xaman-app/environment-probe.json, tests/logic/security_models/crypto_exchange/test_xaman_environment_probe.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_environment_probe.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_xaman_environment.py --corpus-manifest security_ir_artifacts/corpora/xaman-app/source-manifest.json --out security_ir_artifacts/corpora/xaman-app/environment-probe.json
- Acceptance: Record Node and npm requirements, React Native build assumptions, iOS and Android native assumptions, dependency lockfile digest, TypeScript config, Detox or e2e availability, solver paths, and missing dependency blockers.

## PORTAL-CXTP-062 Restore SecurityModelIR schema and source coverage gates

- Status: completed
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: PORTAL-CXTP-056, PORTAL-CXTP-059, PORTAL-CXTP-088
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/ir/schema.py, ipfs_datasets_py/logic/security_models/crypto_exchange/ir/canonicalize.py, docs/security_verification/code_to_ir_evidence_matrix.md, tests/logic/security_models/crypto_exchange/test_ir_schema.py, tests/logic/security_models/crypto_exchange/test_code_to_ir_coverage.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_ir_schema.py tests/logic/security_models/crypto_exchange/test_code_to_ir_coverage.py -q
- Acceptance: Restore a typed IR with assumptions, evidence, claims, proof obligations, disproof vectors, runtime traces, solver results, CIDs, and fail-closed coverage checks for every production and Xaman security domain.

## PORTAL-CXTP-063 Extend extractor for Xaman React Native TypeScript corpus

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_source_extractor.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python -m ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_source_extractor --manifest security_ir_artifacts/corpora/xaman-app/source-manifest.json --out security_ir_artifacts/corpora/xaman-app/source-coverage.json
- Priority: P0
- Track: platform
- Depends on: PORTAL-CXTP-060, PORTAL-CXTP-062
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/extractors/xaman_source_extractor.py, security_ir_artifacts/corpora/xaman-app/source-coverage.json, tests/logic/security_models/crypto_exchange/test_xaman_source_extractor.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_source_extractor.py -q
- Acceptance: Parse Xaman path aliases and TypeScript or TSX files, classify security-relevant modules in services, store, payload, ledger, vault, auth UI, and e2e flows, and emit reviewed coverage gaps instead of silently ignoring unsupported files.

## PORTAL-CXTP-064 Model Xaman account, vault, storage, and authentication facts

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_wallet_auth_model.py -q
- Priority: P0
- Track: wallet
- Depends on: PORTAL-CXTP-060, PORTAL-CXTP-063
- Outputs: docs/security_verification/xaman_wallet_auth_model.md, security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json, tests/logic/security_models/crypto_exchange/test_xaman_wallet_auth_model.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_wallet_auth_model.py -q
- Acceptance: Extract reviewed facts for account storage, vault access, authentication overlays, biometric or passcode gates, key custody boundaries, signing preconditions, and unsupported source gaps marked `NOT_MODELED`.

## PORTAL-CXTP-065 Model Xaman payload and sign-request lifecycle

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_payload_lifecycle.py -q
- Priority: P0
- Track: wallet
- Depends on: PORTAL-CXTP-060, PORTAL-CXTP-063
- Outputs: docs/security_verification/xaman_payload_lifecycle_model.md, security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json, tests/logic/security_models/crypto_exchange/test_xaman_payload_lifecycle.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_payload_lifecycle.py -q
- Acceptance: Model payload creation, QR and deep-link intake, review UI, approval, rejection, expiration, replay controls, network binding, signing, backend patching, and broadcast boundaries with source evidence.

## PORTAL-CXTP-066 Model XRPL transaction semantics from Xaman ledger code

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_model.py -q
- Priority: P0
- Track: ledger
- Depends on: PORTAL-CXTP-060, PORTAL-CXTP-063
- Outputs: docs/security_verification/xaman_xrpl_transaction_model.md, security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json, tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_model.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_model.py -q
- Acceptance: Model account, destination, amount, fee, sequence, network, memo, issued-currency, trustline, multisign, and transaction-type constraints needed for XRPL signing safety claims.

## PORTAL-CXTP-067 Define Xaman XRPL security claims and assumptions

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_claims.py -q
- Priority: P0
- Track: wallet
- Depends on: PORTAL-CXTP-064, PORTAL-CXTP-065, PORTAL-CXTP-066
- Outputs: docs/security_verification/xaman_security_claims.md, security_ir_artifacts/corpora/xaman-app/security-claims.json, tests/logic/security_models/crypto_exchange/test_xaman_security_claims.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_claims.py -q
- Acceptance: Define blocking and high-risk claims for custody, authentication, payload integrity, replay prevention, network binding, transaction semantics, backend trust, runtime equivalence, and proof-consumer policy, with every assumption explicitly evidenced or marked blocking.

## PORTAL-CXTP-068 Generate Xaman SecurityModelIR baseline

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_model_ir.py -q
- Priority: P0
- Track: platform
- Depends on: PORTAL-CXTP-062, PORTAL-CXTP-067
- Outputs: security_ir_artifacts/corpora/xaman-app/security-model-ir.json, security_ir_artifacts/corpora/xaman-app/security-model-ir.cid, docs/security_verification/xaman_security_model_ir.md, tests/logic/security_models/crypto_exchange/test_xaman_security_model_ir.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_model_ir.py -q
- Acceptance: Build a canonical IR that binds corpus commit, environment probe, reviewed source facts, assumptions, claims, solver obligations, disproof vectors, and deterministic CID output.

## PORTAL-CXTP-069 Emit SMT-LIB and run Z3/CVC5 differential proofs

- Status: completed
- Completion: manual
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-068, PORTAL-CXTP-089
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/compilers/to_smtlib.py, ipfs_datasets_py/logic/security_models/crypto_exchange/runners/cvc5_runner.py, security_ir_artifacts/corpora/xaman-app/smtlib/manifest.json, security_ir_artifacts/corpora/xaman-app/proof-reports/z3-cvc5-differential.json, tests/logic/security_models/crypto_exchange/test_xaman_smt_differential.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_smt_differential.py -q
- Acceptance: Cross-check all blocking and high Xaman claims with Z3 and CVC5, attach SMT-LIB artifacts, reject unsupported theories and disagreements, and classify every result as proved, disproved, unknown, or blocked.

## PORTAL-CXTP-070 Build mutation and disproof counterexample suite

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_disproof_vectors.py -q
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-067, PORTAL-CXTP-068
- Outputs: security_ir_artifacts/corpora/xaman-app/disproof-vectors.json, security_ir_artifacts/corpora/xaman-app/counterexample-report.json, tests/logic/security_models/crypto_exchange/test_xaman_disproof_vectors.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_disproof_vectors.py -q
- Acceptance: Mutate assumptions, remove auth preconditions, stale evidence, wrong network, replay payloads, downgraded solvers, unsupported XRPL semantics, and backend trust failures, and verify that expected counterexamples are found or explicitly blocked.

## PORTAL-CXTP-071 Add TLA/Apalache workflow checks for Xaman signing

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_lean_solver_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_lean_solver_lane.py --out security_ir_artifacts/environment/lean-solver-lane-report.json
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-065, PORTAL-CXTP-067, PORTAL-CXTP-086
- Outputs: security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla, security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json, docs/security_verification/xaman_tla_workflow.md, tests/logic/security_models/crypto_exchange/test_xaman_tla_workflow.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_tla_workflow.py -q
- Acceptance: Check temporal properties for fetch, review, approval, revalidation, signing, rejection, expiration, replay, network binding, and broadcast transitions, and mark Apalache absence as a solver blocker.

## PORTAL-CXTP-072 Add Tamarin/ProVerif protocol checks for payload flow

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_apalache_solver_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_apalache_solver_lane.py --out security_ir_artifacts/environment/apalache-solver-lane-report.json
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-065, PORTAL-CXTP-067, PORTAL-CXTP-086
- Outputs: security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy, security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json, docs/security_verification/xaman_protocol_model.md, tests/logic/security_models/crypto_exchange/test_xaman_protocol_projection.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_protocol_projection.py -q
- Acceptance: Model payload session identities, requester binding, QR/deep-link intake, replay, secrets, signatures, and backend trust boundaries, and reject claims that require unavailable protocol evidence.

## PORTAL-CXTP-073 Add Lean/Coq proof-consumer invariants

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_protocol_solver_lanes.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_protocol_solver_lanes.py --out security_ir_artifacts/environment/protocol-solver-lane-report.json
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-067, PORTAL-CXTP-086
- Outputs: security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean, security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json, docs/security_verification/xaman_proof_consumer_invariants.md, tests/logic/security_models/crypto_exchange/test_xaman_proof_consumer_invariants.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_proof_consumer_invariants.py -q
- Acceptance: Prove or check that accepted proof receipts bind model CID, claim ID, report CID, solver identity, assumptions, reviewed source evidence, corpus commit, and fresh environment probe, and cannot accept disproved, unknown, not-modeled, stale, or missing-solver outcomes.

## PORTAL-CXTP-074 Ingest Xaman e2e and runtime traces

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python -m ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_runtime_trace_ingestor --out security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json
- Priority: P1
- Track: runtime
- Depends on: PORTAL-CXTP-061, PORTAL-CXTP-065, PORTAL-CXTP-066
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/extractors/xaman_runtime_trace_ingestor.py, security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json, docs/security_verification/xaman_runtime_trace_assumptions.md, tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py -q
- Acceptance: Convert e2e and runtime events into monitor facts for payload intake, review, auth, signing, rejection, expiration, network binding, and broadcast, while marking absent real-device traces as blocking runtime-equivalence evidence.

## PORTAL-CXTP-075 Produce Xaman assurance packet and release decision

- Status: completed
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-069, PORTAL-CXTP-070, PORTAL-CXTP-071, PORTAL-CXTP-072, PORTAL-CXTP-073, PORTAL-CXTP-074
- Outputs: security_ir_artifacts/corpora/xaman-app/assurance-packet.json, docs/security_verification/xaman_assurance_packet.md, docs/security_verification/xaman_release_decision.md, tests/logic/security_models/crypto_exchange/test_xaman_assurance_packet.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_assurance_packet.py -q
- Acceptance: Bundle model CID, corpus commit, manifest, environment probe, proof reports, disproof reports, solver matrix, runtime traces, open blockers, assumptions, and a fail-closed release decision.

## PORTAL-CXTP-076 Bridge Xaman artifacts into production-blocker removal

- Status: completed
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-075
- Outputs: docs/security_verification/xaman_to_production_blocker_bridge.md, security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json, tests/logic/security_models/crypto_exchange/test_xaman_production_blocker_bridge.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_production_blocker_bridge.py -q
- Acceptance: Map Xaman evidence to production blockers, distinguish source-corpus evidence from deployed-app evidence, and list every blocker that still needs production source, build, runtime, environment, or human review.

## PORTAL-CXTP-077 Collect production environment evidence

- Status: blocked
- Completion: manual
- Priority: P0
- Track: ops
- Blocked reason: Requires deployed wallet and exchange environment details, host/container images, HSM or custody configuration, chain node endpoints, CI/CD attestations, and runtime policies that are not present in this repository.
- Depends on: PORTAL-CXTP-059
- Outputs: docs/security_verification/production_environment_profile.md, security_ir_artifacts/production/environment-profile.json
- Validation: test -f docs/security_verification/production_environment_profile.md; test -f security_ir_artifacts/production/environment-profile.json
- Acceptance: Record exact production compute, wallet, exchange, custody, network, chain-node, CI/CD, monitoring, and operational assumptions with owners and freshness windows.

## PORTAL-CXTP-078 Inventory deployed wallet, exchange, API, and policy sources

- Status: blocked
- Completion: manual
- Priority: P0
- Track: ops
- Blocked reason: Requires production wallet/exchange source repositories or immutable source snapshots and API schemas that are not present in this repository.
- Depends on: PORTAL-CXTP-059
- Outputs: docs/security_verification/production_source_inventory.md, security_ir_artifacts/production/source-inventory.json
- Validation: test -f docs/security_verification/production_source_inventory.md; test -f security_ir_artifacts/production/source-inventory.json
- Acceptance: Inventory every production source, schema, smart contract, custody policy, exchange ledger path, wallet flow, and deployment commit needed for proof-boundary completeness.

## PORTAL-CXTP-079 Generate reviewed production SecurityModelIR candidate

- Status: blocked
- Completion: manual
- Priority: P0
- Track: platform
- Blocked reason: Requires production source inventory, environment profile, deployed runtime traces, and named reviewer signoff before a production model can be trusted.
- Depends on: PORTAL-CXTP-077, PORTAL-CXTP-078
- Outputs: security_ir_artifacts/production/security-model-ir.json, security_ir_artifacts/production/security-model-ir.cid, docs/security_verification/production_security_model_ir.md
- Validation: test -f security_ir_artifacts/production/security-model-ir.json; test -f security_ir_artifacts/production/security-model-ir.cid
- Acceptance: Produce a reviewed production IR with complete domains for wallet custody, exchange ledger, withdrawals, deposits, internal accounting, API auth, runtime monitoring, and proof-consumer policy.

## PORTAL-CXTP-080 Enforce required production domains and claim minimums

- Status: blocked
- Completion: manual
- Priority: P0
- Track: quality
- Blocked reason: Requires the reviewed production SecurityModelIR candidate and production claim owners.
- Depends on: PORTAL-CXTP-079
- Outputs: docs/security_verification/production_claim_gate.md, security_ir_artifacts/production/claim-gate-report.json
- Validation: test -f docs/security_verification/production_claim_gate.md; test -f security_ir_artifacts/production/claim-gate-report.json
- Acceptance: Fail closed unless the production model contains all required wallet, exchange, custody, API, ledger, runtime, disproof, and proof-consumer claims.

## PORTAL-CXTP-081 Run production fail-closed proof baseline

- Status: blocked
- Completion: manual
- Priority: P0
- Track: solver
- Blocked reason: Requires reviewed production SecurityModelIR, solver dependency probe, source evidence, and environment evidence.
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-080, PORTAL-CXTP-089
- Outputs: security_ir_artifacts/production/proof-reports/baseline.json, docs/security_verification/production_proof_baseline.md
- Validation: test -f security_ir_artifacts/production/proof-reports/baseline.json; test -f docs/security_verification/production_proof_baseline.md
- Acceptance: Run configured solvers against production claims and reject release on any unknown, unsupported, stale, not-modeled, missing-solver, or disproved blocking claim.

## PORTAL-CXTP-082 Run production disproof and mutation suite

- Status: blocked
- Completion: manual
- Priority: P0
- Track: solver
- Blocked reason: Requires reviewed production claims, model, disproof vectors, and solver availability.
- Depends on: PORTAL-CXTP-080, PORTAL-CXTP-081
- Outputs: security_ir_artifacts/production/disproof-report.json, docs/security_verification/production_disproof_suite.md
- Validation: test -f security_ir_artifacts/production/disproof-report.json; test -f docs/security_verification/production_disproof_suite.md
- Acceptance: Prove that known-bad variants fail by injecting replay, auth bypass, double-spend, accounting mismatch, stale receipt, missing custody approval, signer downgrade, and chain-network mismatch counterexamples.

## PORTAL-CXTP-083 Wire production runtime trace evidence

- Status: blocked
- Completion: manual
- Priority: P0
- Track: runtime
- Blocked reason: Requires sanitized production runtime traces, e2e traces, schemas, stream names, and owner-approved freshness windows.
- Depends on: PORTAL-CXTP-077, PORTAL-CXTP-079
- Outputs: docs/security_verification/runtime_event_mapping.md, security_ir_artifacts/production/runtime-trace-report.json
- Validation: test -f docs/security_verification/runtime_event_mapping.md; test -f security_ir_artifacts/production/runtime-trace-report.json
- Acceptance: Map production traces to model events, preserve identifiers for counterexamples, and reject release when runtime evidence is absent, stale, or schema-incompatible.

## PORTAL-CXTP-084 Refresh production blockers and handoff checklist

- Status: blocked
- Completion: manual
- Priority: P0
- Track: ops
- Blocked reason: Requires all production source, environment, runtime, proof, disproof, and reviewer inputs.
- Depends on: PORTAL-CXTP-077, PORTAL-CXTP-078, PORTAL-CXTP-079, PORTAL-CXTP-080, PORTAL-CXTP-081, PORTAL-CXTP-082, PORTAL-CXTP-083
- Outputs: docs/security_verification/production_security_handoff_checklist.md, security_ir_artifacts/production/release-blockers.json
- Validation: test -f docs/security_verification/production_security_handoff_checklist.md; test -f security_ir_artifacts/production/release-blockers.json
- Acceptance: List every remaining external production input with owners, evidence paths, freshness windows, and non-negotiable fail-closed gates.

## PORTAL-CXTP-085 Build production evidence intake scaffold

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_evidence_intake.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/validate_production_evidence_bundle.py --bundle security_ir_artifacts/production/evidence-bundle.json --out security_ir_artifacts/production/evidence-bundle-report.json
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-056, PORTAL-CXTP-059, PORTAL-CXTP-088
- Outputs: docs/security_verification/production_evidence_intake.md, scripts/ops/security_verification/validate_production_evidence_bundle.py, security_ir_artifacts/production/evidence-bundle.schema.json, tests/logic/security_models/crypto_exchange/test_production_evidence_intake.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_evidence_intake.py -q
- Acceptance: Create an intake schema and validator for production source snapshots, environment evidence, runtime traces, owner signoff, solver reports, and freshness metadata so blocked production tasks can be unblocked by a concrete bundle.

## PORTAL-CXTP-086 Build optional solver installer and blocker remover

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_optional_solver_installer.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/install_optional_theorem_solvers.py --out security_ir_artifacts/environment/optional-solver-install-report.json
- Priority: P1
- Track: ops
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-088
- Outputs: docs/security_verification/optional_solver_installation.md, scripts/ops/security_verification/install_optional_theorem_solvers.py, security_ir_artifacts/environment/optional-solver-install-report.json, tests/logic/security_models/crypto_exchange/test_optional_solver_installer.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_optional_solver_installer.py -q
- Acceptance: Provide safe install/probe commands for Apalache, Tamarin, ProVerif, Lean, and Coq, record unsupported platforms, and convert missing optional solvers into explicit blocked or degraded proof lanes rather than silent success.

## PORTAL-CXTP-087 Wire taskboard integrity into CI and supervisor preflight

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_taskboard_preflight.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/preflight_crypto_exchange_taskboard.py --taskboard docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md --state data/crypto_exchange_theorem_prover/state/cxtp_task_state.json --out security_ir_artifacts/recovery/taskboard-preflight-report.json
- Priority: P1
- Track: quality
- Depends on: PORTAL-CXTP-057, PORTAL-CXTP-088
- Outputs: .github/workflows/crypto-exchange-security-verification.yml, scripts/ops/security_verification/preflight_crypto_exchange_taskboard.py, docs/security_verification/taskboard_preflight_ci.md, tests/logic/security_models/crypto_exchange/test_taskboard_preflight.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_taskboard_preflight.py -q
- Acceptance: Make CI and supervisor preflight fail when the taskboard has no parseable tasks, source files disappear, required artifacts are absent, statuses contradict evidence, or production blockers are accidentally treated as release-acceptable.

## PORTAL-CXTP-090 Remediate Lean optional proof-consumer solver lane

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_coq_solver_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_coq_solver_lane.py --out security_ir_artifacts/environment/coq-solver-lane-report.json
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-073, PORTAL-CXTP-086
- Outputs: docs/security_verification/lean_proof_consumer_solver_lane.md, scripts/ops/security_verification/probe_lean_solver_lane.py, security_ir_artifacts/environment/lean-solver-lane-report.json, tests/logic/security_models/crypto_exchange/test_lean_solver_lane.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_lean_solver_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_lean_solver_lane.py --out security_ir_artifacts/environment/lean-solver-lane-report.json
- Acceptance: Probe Lean and Lake, compile-check the Xaman proof-consumer kernel when present, and record missing or unusable Lean as an explicit degraded or blocked optional lane rather than silent proof acceptance.

## PORTAL-CXTP-091 Provision Apalache TLA model-checker lane

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_apalache_solver_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_apalache_solver_lane.py --out security_ir_artifacts/environment/apalache-solver-lane-report.json
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-071, PORTAL-CXTP-086
- Outputs: docs/security_verification/apalache_tla_solver_lane.md, scripts/ops/security_verification/probe_apalache_solver_lane.py, security_ir_artifacts/environment/apalache-solver-lane-report.json, tests/logic/security_models/crypto_exchange/test_apalache_solver_lane.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_apalache_solver_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_apalache_solver_lane.py --out security_ir_artifacts/environment/apalache-solver-lane-report.json
- Acceptance: Detect or provision Apalache for the Xaman TLA model-checking lane, record exact executable/version evidence, and keep TLA coverage blocked or degraded when the solver is unavailable.

## PORTAL-CXTP-092 Provision Tamarin and ProVerif protocol solver lanes

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_protocol_solver_lanes.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_protocol_solver_lanes.py --out security_ir_artifacts/environment/protocol-solver-lane-report.json
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-072, PORTAL-CXTP-086
- Outputs: docs/security_verification/protocol_solver_lanes.md, scripts/ops/security_verification/probe_protocol_solver_lanes.py, security_ir_artifacts/environment/protocol-solver-lane-report.json, tests/logic/security_models/crypto_exchange/test_protocol_solver_lanes.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_protocol_solver_lanes.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_protocol_solver_lanes.py --out security_ir_artifacts/environment/protocol-solver-lane-report.json
- Acceptance: Detect or provision Tamarin and ProVerif, run protocol-lane probes against the Xaman payload-flow model when present, and record missing solvers as explicit protocol proof gaps.

## PORTAL-CXTP-093 Provision Coq proof-kernel solver lane

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_coq_solver_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_coq_solver_lane.py --out security_ir_artifacts/environment/coq-solver-lane-report.json
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-073, PORTAL-CXTP-086
- Outputs: docs/security_verification/coq_proof_kernel_solver_lane.md, scripts/ops/security_verification/probe_coq_solver_lane.py, security_ir_artifacts/environment/coq-solver-lane-report.json, tests/logic/security_models/crypto_exchange/test_coq_solver_lane.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_coq_solver_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_coq_solver_lane.py --out security_ir_artifacts/environment/coq-solver-lane-report.json
- Acceptance: Detect or provision Coq for proof-kernel cross-checking, capture exact toolchain evidence, and keep proof-kernel coverage blocked or degraded when Coq is unavailable.

## PORTAL-CXTP-094 Generate production evidence packets for each remaining blocker

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_blocker_evidence_packets.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/generate_production_blocker_evidence_packets.py --out security_ir_artifacts/production/blocker-evidence-packets.json
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-076, PORTAL-CXTP-085
- Outputs: docs/security_verification/production_blocker_evidence_packets.md, scripts/ops/security_verification/generate_production_blocker_evidence_packets.py, security_ir_artifacts/production/blocker-evidence-packets.json, tests/logic/security_models/crypto_exchange/test_production_blocker_evidence_packets.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_blocker_evidence_packets.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/generate_production_blocker_evidence_packets.py --out security_ir_artifacts/production/blocker-evidence-packets.json
- Acceptance: Generate one explicit evidence packet per remaining production blocker, preserving owner, freshness, source, environment, runtime, solver, and human-review requirements without marking production secure.

## PORTAL-CXTP-095 Build guarded production blocker status updater

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_blocker_status_updater.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/update_production_blocker_status.py --dry-run --packets security_ir_artifacts/production/blocker-evidence-packets.json --out security_ir_artifacts/production/blocker-status-update-report.json
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-085, PORTAL-CXTP-094
- Outputs: docs/security_verification/production_blocker_status_updater.md, scripts/ops/security_verification/update_production_blocker_status.py, security_ir_artifacts/production/blocker-status-update-report.json, tests/logic/security_models/crypto_exchange/test_production_blocker_status_updater.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_blocker_status_updater.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/update_production_blocker_status.py --dry-run --packets security_ir_artifacts/production/blocker-evidence-packets.json --out security_ir_artifacts/production/blocker-status-update-report.json
- Acceptance: Update production blocker status only from validated evidence packets, reject stale or incomplete inputs, and preserve fail-closed release blocking when production evidence is absent.

## PORTAL-CXTP-096 Protect appended solver and production unblocker tasks

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_appended_cxtp_task_retention.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/check_appended_cxtp_tasks.py --taskboard docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md --out security_ir_artifacts/recovery/appended-task-retention-report.json
- Priority: P0
- Track: quality
- Depends on: PORTAL-CXTP-057, PORTAL-CXTP-087
- Outputs: docs/security_verification/appended_task_retention_runbook.md, scripts/ops/security_verification/check_appended_cxtp_tasks.py, security_ir_artifacts/recovery/appended-task-retention-report.json, tests/logic/security_models/crypto_exchange/test_appended_cxtp_task_retention.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_appended_cxtp_task_retention.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/check_appended_cxtp_tasks.py --taskboard docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md --out security_ir_artifacts/recovery/appended-task-retention-report.json
- Acceptance: Fail closed when appended tasks PORTAL-CXTP-090 through PORTAL-CXTP-097 disappear, lose required metadata, or are marked complete without evidence, and keep downstream solver or production unblocker tasks blocked until the report passes.

## PORTAL-CXTP-097 Integrate Leanstral proof-assistant lane

- Status: completed
- Completion: manual
- Completion evidence: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_leanstral_proof_assistant_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_leanstral_proof_assistant.py --out security_ir_artifacts/environment/leanstral-proof-assistant-report.json
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-090, PORTAL-CXTP-096
- Outputs: docs/security_verification/leanstral_proof_assistant_lane.md, scripts/ops/security_verification/probe_leanstral_proof_assistant.py, security_ir_artifacts/environment/leanstral-proof-assistant-report.json, tests/logic/security_models/crypto_exchange/test_leanstral_proof_assistant_lane.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_leanstral_proof_assistant_lane.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_leanstral_proof_assistant.py --out security_ir_artifacts/environment/leanstral-proof-assistant-report.json
- Acceptance: Detect configured Leanstral model routes such as labs-leanstral-1-5, labs-leanstral-2603, or local weights, generate proof-attempt prompts for Xaman Lean kernels, require Lean/Lake compilation for every suggested proof, and record Leanstral output as advisory proof engineering assistance rather than proof authority.

## PORTAL-CXTP-098 Approve staged production evidence collection gate

- Status: blocked
- Completion: manual
- Priority: P0
- Track: governance
- Blocked reason: Requires security release-owner approval for a collection-completeness report that is explicitly distinct from release acceptance; no implementation may weaken the existing fail-closed full bundle validator.
- Depends on: PORTAL-CXTP-085, PORTAL-CXTP-095, PORTAL-CXTP-096
- Outputs: docs/security_verification/production_evidence_generation_plan.md, docs/security_verification/production_evidence_collection_gate.md, security_ir_artifacts/production/collection-gate-report.json, tests/logic/security_models/crypto_exchange/test_production_evidence_collection_gate.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_evidence_collection_gate.py -q
- Acceptance: Define and test a staged collection-completeness report that validates reviewed source, environment, runtime, and owner inputs without accepting a release; preserve `PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED` exclusively for a full bundle with current proof results for every blocking and high claim.

## PORTAL-CXTP-099 Establish production evidence charter, RACI, and secure handling boundary

- Status: blocked
- Completion: manual
- Priority: P0
- Track: governance
- Blocked reason: Requires named production owners, approved evidence stores, data-classification rules, and authority to request redacted production exports.
- Depends on: PORTAL-CXTP-098
- Outputs: docs/security_verification/production_evidence_charter.md, security_ir_artifacts/production/evidence-governance.json, security_ir_artifacts/production/evidence-request-register.json
- Validation: test -f docs/security_verification/production_evidence_charter.md; test -f security_ir_artifacts/production/evidence-governance.json; test -f security_ir_artifacts/production/evidence-request-register.json
- Acceptance: Assign accountable owners for assumptions A1 through A10, source, runtime, proof, review, and release decisions; define approved redaction, retention, secure-reference, freshness, and escalation rules; reject storage of secrets, private keys, tokens, or raw customer data in this repository.

## PORTAL-CXTP-100 Freeze the exact production release target and build provenance

- Status: blocked
- Completion: manual
- Priority: P0
- Track: ops
- Blocked reason: Requires authorized release, deployment, mobile-build, backend-build, smart-contract, and CI/CD provenance exports for the target production release.
- Depends on: PORTAL-CXTP-099
- Outputs: security_ir_artifacts/production/evidence/source/release-target.json, security_ir_artifacts/production/evidence/source/build-provenance.json, docs/security_verification/production_release_target.md
- Validation: test -f security_ir_artifacts/production/evidence/source/release-target.json; test -f security_ir_artifacts/production/evidence/source/build-provenance.json; test -f docs/security_verification/production_release_target.md
- Acceptance: Pin the application version, repository revisions, mobile and backend artifacts, deployment identifiers, CI run IDs, package or SBOM digests, contract addresses or bytecode hashes, environments, chains, and collection time; fail closed on an ambiguous or mutable target.

## PORTAL-CXTP-101 Collect reviewed deployed source snapshots and source-to-claim mappings

- Status: blocked
- Completion: manual
- Priority: P0
- Track: source
- Blocked reason: Requires authorized read access or reviewed redacted exports for deployed wallet, exchange, API, policy, custody, ledger, schema, monitoring, and proof-consumer sources.
- Depends on: PORTAL-CXTP-099, PORTAL-CXTP-100
- Outputs: security_ir_artifacts/production/evidence/source/source-snapshots.json, security_ir_artifacts/production/evidence/source/source-claim-map.json, docs/security_verification/production_source_snapshot_review.md
- Validation: test -f security_ir_artifacts/production/evidence/source/source-snapshots.json; test -f security_ir_artifacts/production/evidence/source/source-claim-map.json; test -f docs/security_verification/production_source_snapshot_review.md
- Acceptance: Record repository, commit, artifact digest, deployment linkage, owner, collection date, review status, and module or line mapping for every blocking or high claim; label any unsupported or absent component `NOT_MODELED` and retain its release block.

## PORTAL-CXTP-102 Collect reviewed environment, custody, and operational assumption evidence

- Status: blocked
- Completion: manual
- Priority: P0
- Track: ops
- Blocked reason: Requires reviewed, sanitized production exports for key custody, signing, databases, nonce service, chain risk, RPC, CI/CD, monitoring, audit, and governance controls.
- Depends on: PORTAL-CXTP-099, PORTAL-CXTP-100
- Outputs: security_ir_artifacts/production/evidence/environment/assumption-evidence.json, security_ir_artifacts/production/evidence/environment/environment-snapshots.json, docs/security_verification/production_assumption_evidence_review.md
- Validation: test -f security_ir_artifacts/production/evidence/environment/assumption-evidence.json; test -f security_ir_artifacts/production/evidence/environment/environment-snapshots.json; test -f docs/security_verification/production_assumption_evidence_review.md
- Acceptance: Resolve assumptions A1 through A10 with owner, evidence reference, collection time, expiry, review, and fail-closed status, covering cryptography, key lifecycle, signing, database and nonce behavior, finality, administrative control, HSM, RPC, audit, and runtime operations.

## PORTAL-CXTP-103 Collect sanitized production runtime traces and event schemas

- Status: blocked
- Completion: manual
- Priority: P0
- Track: runtime
- Blocked reason: Requires an owner-approved sanitized export from production telemetry and real-device or end-to-end release-window traces with stable pseudonymous correlation identifiers.
- Depends on: PORTAL-CXTP-099, PORTAL-CXTP-100
- Outputs: security_ir_artifacts/production/evidence/runtime/trace-manifest.json, security_ir_artifacts/production/evidence/runtime/event-schemas.json, security_ir_artifacts/production/evidence/runtime/sanitized-traces.ndjson, docs/security_verification/production_runtime_collection.md
- Validation: test -f security_ir_artifacts/production/evidence/runtime/trace-manifest.json; test -f security_ir_artifacts/production/evidence/runtime/event-schemas.json; test -f security_ir_artifacts/production/evidence/runtime/sanitized-traces.ndjson; test -f docs/security_verification/production_runtime_collection.md
- Acceptance: Cover payload intake, review, authentication, authorization, signing and refusal, expiration, replay, network binding, broadcast, finality, rejection, cancellation, and audit events; record collection window, source schema, device or deployment provenance, redaction method, owner, and freshness interval.

## PORTAL-CXTP-104 Independently review evidence and obtain owner signoffs

- Status: blocked
- Completion: manual
- Priority: P0
- Track: governance
- Blocked reason: Requires independent reviewer availability and explicit approvals from the accountable production owners named in the evidence charter.
- Depends on: PORTAL-CXTP-099, PORTAL-CXTP-101, PORTAL-CXTP-102, PORTAL-CXTP-103
- Outputs: security_ir_artifacts/production/evidence/reviews/owner-signoffs.json, security_ir_artifacts/production/evidence/reviews/independent-review.json, docs/security_verification/production_evidence_review.md
- Validation: test -f security_ir_artifacts/production/evidence/reviews/owner-signoffs.json; test -f security_ir_artifacts/production/evidence/reviews/independent-review.json; test -f docs/security_verification/production_evidence_review.md
- Acceptance: Verify artifact digests, release-target consistency, source-to-claim coverage, redaction safety, timestamp freshness, and assumption validity; retain rejected or qualified review findings as release blockers instead of editing them away.

## PORTAL-CXTP-105 Assemble and validate the reviewed collection-stage evidence manifest

- Status: waiting
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-098, PORTAL-CXTP-100, PORTAL-CXTP-101, PORTAL-CXTP-102, PORTAL-CXTP-103, PORTAL-CXTP-104
- Outputs: security_ir_artifacts/production/evidence-bundle.collection.json, security_ir_artifacts/production/collection-gate-report.json, docs/security_verification/production_collection_manifest.md
- Validation: test -f security_ir_artifacts/production/evidence-bundle.collection.json; test -f security_ir_artifacts/production/collection-gate-report.json; test -f docs/security_verification/production_collection_manifest.md
- Acceptance: Build a digest-bound, fresh, human-reviewed source, environment, runtime, and owner-signoff manifest; collection validation may report readiness for model construction but must state that release acceptance and proof coverage remain pending.

## PORTAL-CXTP-106 Materialize reviewed production environment and source inventory outputs

- Status: waiting
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: PORTAL-CXTP-101, PORTAL-CXTP-102, PORTAL-CXTP-104, PORTAL-CXTP-105
- Outputs: docs/security_verification/production_environment_profile.md, security_ir_artifacts/production/environment-profile.json, docs/security_verification/production_source_inventory.md, security_ir_artifacts/production/source-inventory.json
- Validation: test -f docs/security_verification/production_environment_profile.md; test -f security_ir_artifacts/production/environment-profile.json; test -f docs/security_verification/production_source_inventory.md; test -f security_ir_artifacts/production/source-inventory.json
- Acceptance: Replace scaffolds with reviewed evidence bound to the frozen release target, preserve owner and freshness metadata for every assumption and source mapping, and produce the direct evidence inputs required by PORTAL-CXTP-077 and PORTAL-CXTP-078 without asserting production security.

## PORTAL-CXTP-107 Prepare production SecurityModelIR formalization inputs and runtime mapping

- Status: waiting
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: PORTAL-CXTP-103, PORTAL-CXTP-105, PORTAL-CXTP-106
- Outputs: security_ir_artifacts/production/evidence/source/model-input-map.json, security_ir_artifacts/production/evidence/runtime/event-model-map.json, docs/security_verification/production_model_input_review.md
- Validation: test -f security_ir_artifacts/production/evidence/source/model-input-map.json; test -f security_ir_artifacts/production/evidence/runtime/event-model-map.json; test -f docs/security_verification/production_model_input_review.md
- Acceptance: Map every required wallet, exchange, custody, API, ledger, runtime, audit, and proof-consumer fact to a typed SecurityModelIR input, proof obligation, assumption, and trace event; retain every unresolved mapping as a release-blocking gap for PORTAL-CXTP-079 and PORTAL-CXTP-083.

## PORTAL-CXTP-108 Execute the reviewed production formalization and proof work packages

- Status: waiting
- Completion: manual
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-077, PORTAL-CXTP-078, PORTAL-CXTP-079, PORTAL-CXTP-080, PORTAL-CXTP-081, PORTAL-CXTP-082, PORTAL-CXTP-083, PORTAL-CXTP-107
- Outputs: security_ir_artifacts/production/evidence/solver/solver-run-manifest.json, docs/security_verification/production_solver_execution_record.md
- Validation: test -f security_ir_artifacts/production/evidence/solver/solver-run-manifest.json; test -f docs/security_verification/production_solver_execution_record.md
- Acceptance: Record the immutable model CID, solver executable and version, command, evidence digest set, claim outcome, proof or counterexample artifact, and reviewer for every production proof and disproof run; only `prove` outcomes for all blocking and high claims may be used in the full evidence bundle.

## PORTAL-CXTP-109 Assemble the full production evidence bundle and perform guarded status update

- Status: waiting
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-104, PORTAL-CXTP-106, PORTAL-CXTP-108
- Outputs: security_ir_artifacts/production/evidence-bundle.json, security_ir_artifacts/production/evidence-bundle-report.json, security_ir_artifacts/production/blocker-status-update-report.json
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/validate_production_evidence_bundle.py --bundle security_ir_artifacts/production/evidence-bundle.json --out security_ir_artifacts/production/evidence-bundle-report.json; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/update_production_blocker_status.py --dry-run --packets security_ir_artifacts/production/blocker-evidence-packets.json --out security_ir_artifacts/production/blocker-status-update-report.json
- Acceptance: Require `overall_status: pass`, `security_decision: PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED`, current human-reviewed evidence, approved signoffs, and `prove` for every blocking or high claim before any status update; retain every failure as a production release block.

## PORTAL-CXTP-110 Complete production release handoff or preserve the fail-closed decision

- Status: waiting
- Completion: manual
- Priority: P0
- Track: governance
- Depends on: PORTAL-CXTP-084, PORTAL-CXTP-109
- Outputs: docs/security_verification/production_security_handoff_checklist.md, security_ir_artifacts/production/release-blockers.json, docs/security_verification/production_evidence_handoff_record.md
- Validation: test -f docs/security_verification/production_security_handoff_checklist.md; test -f security_ir_artifacts/production/release-blockers.json; test -f docs/security_verification/production_evidence_handoff_record.md
- Acceptance: Reconcile evidence, model, proof, disproof, runtime, freshness, ownership, and release-policy outcomes; issue a handoff only when all fail-closed gates pass, otherwise preserve a precise non-secure decision and the owner/action needed to clear each remaining blocker.

## PORTAL-CXTP-111 Publish production blocker prerequisite matrix

- Status: completed
- Completion: manual
- Completion evidence: test -f docs/security_verification/production_unblock_prerequisite_matrix.md
- Priority: P0
- Track: planning
- Depends on: PORTAL-CXTP-094, PORTAL-CXTP-095
- Outputs: docs/security_verification/production_unblock_prerequisite_matrix.md
- Validation: test -f docs/security_verification/production_unblock_prerequisite_matrix.md
- Acceptance: Document the source, environment, runtime, review, research, primary-solver, optional-solver, and operational inputs required by every remaining production blocker; distinguish current tool availability from evidence that must come from the deployed release.

## PORTAL-CXTP-112 Research target-specific chain, asset, finality, and RPC trust assumptions

- Status: blocked
- Completion: manual
- Priority: P0
- Track: research
- Blocked reason: Requires the pinned production chain and asset scope, current operator policies, incident history, and accountable chain-risk and infrastructure owners.
- Depends on: PORTAL-CXTP-099, PORTAL-CXTP-100, PORTAL-CXTP-111
- Outputs: security_ir_artifacts/production/evidence/environment/chain-risk-research.json, docs/security_verification/production_chain_risk_assumptions.md
- Validation: test -f security_ir_artifacts/production/evidence/environment/chain-risk-research.json; test -f docs/security_verification/production_chain_risk_assumptions.md
- Acceptance: Record target-specific consensus/finality thresholds, reorganization and rollback behavior, asset support limits, RPC provider trust, disagreement/fallback rules, stale-data bounds, evidence sources, review dates, owners, and every unresolved assumption; feed reviewed results into PORTAL-CXTP-077, PORTAL-CXTP-079, and PORTAL-CXTP-082.

## PORTAL-CXTP-113 Research custody, signing, key-management, and privileged-control assumptions

- Status: blocked
- Completion: manual
- Priority: P0
- Track: research
- Blocked reason: Requires reviewed access to the actual wallet vault, signing, HSM/key-manager, policy-engine, administration, and break-glass control documentation and owners.
- Depends on: PORTAL-CXTP-099, PORTAL-CXTP-100, PORTAL-CXTP-111
- Outputs: security_ir_artifacts/production/evidence/environment/custody-control-research.json, docs/security_verification/production_custody_control_assumptions.md
- Validation: test -f security_ir_artifacts/production/evidence/environment/custody-control-research.json; test -f docs/security_verification/production_custody_control_assumptions.md
- Acceptance: Establish the deployed cryptographic choices, entropy/key lifecycle, approval binding, canonicalization, HSM attestation/refusal semantics, administrative quorum, revocation, and emergency controls, including sources, owners, expiry, and open assumptions for PORTAL-CXTP-077, PORTAL-CXTP-079, and PORTAL-CXTP-081.

## PORTAL-CXTP-114 Research exchange accounting, database, nonce, runtime, and audit assumptions

- Status: blocked
- Completion: manual
- Priority: P0
- Track: research
- Blocked reason: Requires reviewed production architecture, schema, transaction, nonce, monitoring, audit, and privacy-preserving trace-export documentation from the responsible engineering and compliance owners.
- Depends on: PORTAL-CXTP-099, PORTAL-CXTP-100, PORTAL-CXTP-111
- Outputs: security_ir_artifacts/production/evidence/environment/ledger-runtime-research.json, docs/security_verification/production_ledger_runtime_assumptions.md
- Validation: test -f security_ir_artifacts/production/evidence/environment/ledger-runtime-research.json; test -f docs/security_verification/production_ledger_runtime_assumptions.md
- Acceptance: Establish database isolation, reservations, retries, idempotency, nonce uniqueness, accounting and settlement semantics, deployment/runtime behavior, event schemas, audit tamper-evidence, retention, and pseudonymization controls; map conclusions and unknowns to PORTAL-CXTP-077, PORTAL-CXTP-079, PORTAL-CXTP-082, and PORTAL-CXTP-083.

## PORTAL-CXTP-115 Lock and re-probe the primary production proof worker

- Status: waiting
- Completion: manual
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-089, PORTAL-CXTP-100, PORTAL-CXTP-111
- Outputs: security_ir_artifacts/production/proof-worker-lock.json, security_ir_artifacts/production/proof-worker-probe.json, docs/security_verification/production_proof_worker.md
- Validation: test -f security_ir_artifacts/production/proof-worker-lock.json; test -f security_ir_artifacts/production/proof-worker-probe.json; test -f docs/security_verification/production_proof_worker.md
- Acceptance: Use a dedicated reproducible worker to record OS/architecture, Python, Node, TypeScript, Z3, CVC5, and Lean paths, versions, package or binary digests, environment overrides, and proof command environment; remediate a missing or changed required dependency before PORTAL-CXTP-081, while recording Z3/CVC5 as the required differential baseline.

## PORTAL-CXTP-116 Decide and, only when required, provision optional proof coverage solvers

- Status: waiting
- Completion: manual
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-086, PORTAL-CXTP-091, PORTAL-CXTP-092, PORTAL-CXTP-093, PORTAL-CXTP-112, PORTAL-CXTP-113, PORTAL-CXTP-114
- Outputs: security_ir_artifacts/production/optional-solver-coverage-decision.json, docs/security_verification/production_optional_solver_coverage.md
- Validation: test -f security_ir_artifacts/production/optional-solver-coverage-decision.json; test -f docs/security_verification/production_optional_solver_coverage.md
- Acceptance: For each target claim, decide whether Apalache, Tamarin, ProVerif, or Coq is required by the approved threat model; when required, install from a reviewed source, pin executable/version/digest, run the lane, and record its result. Absence of an optional lane must remain an explicit coverage gap and must never be used to accept the release.

## PORTAL-CXTP-117 Rehearse secure, redacted production evidence exports

- Status: blocked
- Completion: manual
- Priority: P0
- Track: ops
- Blocked reason: Requires authorized access to the secure evidence store and telemetry export path, plus approval of the redaction and pseudonymization method by security, privacy, and operational owners.
- Depends on: PORTAL-CXTP-099, PORTAL-CXTP-100, PORTAL-CXTP-101, PORTAL-CXTP-102, PORTAL-CXTP-103, PORTAL-CXTP-111
- Outputs: security_ir_artifacts/production/evidence/export-rehearsal-report.json, docs/security_verification/production_evidence_export_rehearsal.md
- Validation: test -f security_ir_artifacts/production/evidence/export-rehearsal-report.json; test -f docs/security_verification/production_evidence_export_rehearsal.md
- Acceptance: Demonstrate a repeatable export path for source snapshots, configuration attestations, and runtime traces that preserves provenance and stable pseudonymous correlation identifiers, verifies digests, rejects secrets and raw customer data, and is usable by PORTAL-CXTP-101 through PORTAL-CXTP-105.

## PORTAL-CXTP-118 Run production evidence and proof readiness preflight

- Status: waiting
- Completion: manual
- Priority: P0
- Track: quality
- Depends on: PORTAL-CXTP-104, PORTAL-CXTP-106, PORTAL-CXTP-107, PORTAL-CXTP-115, PORTAL-CXTP-117
- Outputs: security_ir_artifacts/production/readiness-preflight-report.json, docs/security_verification/production_readiness_preflight.md
- Validation: test -f security_ir_artifacts/production/readiness-preflight-report.json; test -f docs/security_verification/production_readiness_preflight.md
- Acceptance: Verify the frozen release target, evidence freshness, human review, source-to-claim and event-to-model mappings, required domain coverage, primary solver worker lock, optional-coverage decision, and collection manifest before PORTAL-CXTP-079 through PORTAL-CXTP-083 can consume production inputs; fail closed with a task-and-owner-specific gap list.

## Recovered Xaman Testnet Task Records

The following completed records were recovered from
`data/crypto_exchange_theorem_prover/state/cxtp_task_state.json` and their
durable artifacts. They are retained here so supervisor state, task history,
and release gates use one canonical board.

## PORTAL-CXTP-119 Prepare Firebase-stubbed Xaman public-source Testnet build kit

- Status: completed
- Completion: manual
- Completion evidence: Durable verifier-kit manifest, source assessment, and Firebase-stub test artifacts are retained in the completed supervisor state.
- Priority: P0
- Track: runtime
- Depends on: PORTAL-CXTP-060
- Outputs: scripts/ops/security_verification/xaman_firebase_disabled_testnet.py, docs/security_verification/xaman_firebase_disabled_testnet.md, tests/logic/security_models/crypto_exchange/test_xaman_firebase_disabled_testnet.py, /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit/testnet-build-manifest.json
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_firebase_disabled_testnet.py -q
- Acceptance: Preserve a verifier-only JavaScript Firebase-stub build boundary and classify any residual native Firebase packaging explicitly.

## PORTAL-CXTP-120 Capture redacted Testnet telemetry in DuckDB

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the redacted telemetry report and local DuckDB artifact.
- Priority: P0
- Track: runtime
- Depends on: PORTAL-CXTP-119
- Outputs: security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json, /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/testnet-telemetry.duckdb
- Validation: test -f security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json
- Acceptance: Retain categorical, redacted Testnet telemetry only; reject secrets, addresses, payloads, transaction blobs, credentials, and raw endpoints.

## PORTAL-CXTP-121 Run public-Testnet device trial

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the device-trial report, verifier APK path, and redacted telemetry dependency.
- Priority: P0
- Track: runtime
- Depends on: PORTAL-CXTP-119, PORTAL-CXTP-120
- Outputs: security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json, /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app/android/app/build/outputs/apk/debug/app-x86_64-debug.apk, /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/testnet-telemetry.duckdb
- Validation: test -f security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json
- Acceptance: Bind fresh-emulator, fresh-Testnet-account, and redaction evidence to the verifier-only build without implying native or production equivalence.

## PORTAL-CXTP-122 Map Testnet runtime telemetry to model categories

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the monitor mapping and its scope documentation.
- Priority: P0
- Track: model
- Depends on: PORTAL-CXTP-120, PORTAL-CXTP-121
- Outputs: security_ir_artifacts/corpora/xaman-app/runtime/testnet-monitor-mapping.json, docs/security_verification/xaman_testnet_runtime_mapping.md
- Validation: test -f security_ir_artifacts/corpora/xaman-app/runtime/testnet-monitor-mapping.json
- Acceptance: Map only reviewed categorical Testnet events to SecurityModelIR facts and preserve raw transaction, finality, and backend semantics as not modeled.

## PORTAL-CXTP-123 Repair verifier-build Android compatibility boundary

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the compatibility source and Testnet network-selection report.
- Priority: P1
- Track: runtime
- Depends on: PORTAL-CXTP-119
- Outputs: /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit/react-native-navigation-compat/ReactTypefaceUtils.java, security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json
- Validation: test -f /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit/react-native-navigation-compat/ReactTypefaceUtils.java
- Acceptance: Record verifier-only compatibility changes and retain their non-equivalence to vendor builds.

## PORTAL-CXTP-124 Analyze release R8 dependencies and native boundary

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the release R8 dependency report and analysis.
- Priority: P1
- Track: runtime
- Depends on: PORTAL-CXTP-119
- Outputs: security_ir_artifacts/corpora/xaman-app/runtime/release-r8-dependency-report.json, docs/security_verification/xaman_release_r8_dependency_analysis.md
- Validation: test -f security_ir_artifacts/corpora/xaman-app/runtime/release-r8-dependency-report.json
- Acceptance: Identify retained native dependencies and treat their security behavior as a public-source coverage boundary.

## PORTAL-CXTP-125 Capture Testnet network-selection evidence

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the Testnet network-selection report and capture tooling.
- Priority: P0
- Track: runtime
- Depends on: PORTAL-CXTP-121
- Outputs: docs/security_verification/xaman_testnet_network_selection.md, security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json, scripts/ops/security_verification/capture_xaman_testnet_network_selection.py, tests/logic/security_models/crypto_exchange/test_xaman_testnet_network_selection.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_network_selection.py -q
- Acceptance: Establish categorical `TESTNET`, an allow-listed endpoint decision, and a digest-bound `network_id: 1` observation while rejecting sensitive network inputs.

## PORTAL-CXTP-126 Audit native Firebase packaging boundary

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the native Firebase boundary report and audit test.
- Priority: P0
- Track: runtime
- Depends on: PORTAL-CXTP-119
- Outputs: docs/security_verification/xaman_testnet_native_firebase_boundary.md, security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json, scripts/ops/security_verification/audit_xaman_native_firebase_boundary.py, tests/logic/security_models/crypto_exchange/test_xaman_native_firebase_boundary.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_native_firebase_boundary.py -q
- Acceptance: Report residual native Firebase/Crashlytics packaging as a hard assurance boundary; JavaScript stubbing alone is never a native-security proof.

## PORTAL-CXTP-127 Stabilize Firebase-stubbed Testnet build tooling

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the runnable build-kit script, documentation, and test.
- Priority: P1
- Track: ops
- Depends on: PORTAL-CXTP-119
- Outputs: scripts/ops/security_verification/xaman_firebase_disabled_testnet.py, docs/security_verification/xaman_firebase_disabled_testnet.md, tests/logic/security_models/crypto_exchange/test_xaman_firebase_disabled_testnet.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/xaman_firebase_disabled_testnet.py --help
- Acceptance: Keep verifier build tooling reproducible and clearly limited to the public-source Testnet scope.

## PORTAL-CXTP-128 Ingest redacted Xaman runtime traces

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the runtime trace ingestor, documented assumptions, and tests.
- Priority: P0
- Track: model
- Depends on: PORTAL-CXTP-120, PORTAL-CXTP-122
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/extractors/xaman_runtime_trace_ingestor.py, ipfs_datasets_py/logic/security_models/crypto_exchange/extractors/__init__.py, docs/security_verification/xaman_runtime_trace_assumptions.md, tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py -q
- Acceptance: Reject raw secrets and unrecognized event shapes before conversion into categorical model evidence.

## PORTAL-CXTP-129 Operationalize baseline proof and disproof commands

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains baseline/disproof command wrappers, release-gate documentation, and tests.
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-069, PORTAL-CXTP-070
- Outputs: scripts/ops/security_verification/run_security_ir_disproof_suite.py, scripts/ops/security_verification/run_security_ir_assurance_baseline.py, docs/security_verification/release_gate_runbook.md, ipfs_datasets_py/logic/security_models/crypto_exchange/README.md, tests/logic/security_models/crypto_exchange/test_disproof_ops_script.py, tests/logic/security_models/crypto_exchange/test_assurance_baseline_ops_script.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_disproof_ops_script.py tests/logic/security_models/crypto_exchange/test_assurance_baseline_ops_script.py -q
- Acceptance: Make expected negative controls and fail-closed solver evidence reproducible without treating a green harness as a security verdict.

## PORTAL-CXTP-130 Capture redacted Xaman Testnet transaction lifecycle trial

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the transaction-trial script, report, documentation, and test.
- Priority: P0
- Track: runtime
- Depends on: PORTAL-CXTP-121, PORTAL-CXTP-125, PORTAL-CXTP-126
- Outputs: scripts/ops/security_verification/capture_xaman_testnet_transaction_trial.py, security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-trial-report.json, docs/security_verification/xaman_testnet_transaction_trial.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_transaction_trial.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_transaction_trial.py -q
- Acceptance: Preserve redacted lifecycle categories and Testnet binding while rejecting raw transaction and account material.

## PORTAL-CXTP-131 Review frozen Xaman Testnet SecurityModelIR

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the model, claim trace map, assumptions, documentation, and test.
- Priority: P0
- Track: model
- Depends on: PORTAL-CXTP-122, PORTAL-CXTP-128, PORTAL-CXTP-130
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json, security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json, security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json, docs/security_verification/xaman_testnet_model_review.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_model.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_model.py -q
- Acceptance: Bind every modeled Testnet claim to reviewed inputs and retain unresolved native, backend, XRPL, and runtime assumptions as blocks.

## PORTAL-CXTP-132 Lock Testnet SMT proof worker and CVC5 runner

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the proof-worker lock, CVC5 report, documentation, and test.
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-131
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/proof-worker-lock.json, security_ir_artifacts/corpora/xaman-app/testnet/cvc5-runner-report.json, docs/security_verification/xaman_testnet_smt_worker.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_smt_worker.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_smt_worker.py -q
- Acceptance: Record reproducible SMT solver paths, versions, model identity, and fail-closed differential baseline inputs.

## PORTAL-CXTP-133 Generate Z3/CVC5 Testnet results and counterexamples

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains differential reports, counterexamples, and result documentation.
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-132
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/proof-reports/z3-cvc5-differential.json, security_ir_artifacts/corpora/xaman-app/testnet/counterexamples/, docs/security_verification/xaman_testnet_smt_results.md
- Validation: test -f security_ir_artifacts/corpora/xaman-app/testnet/proof-reports/z3-cvc5-differential.json
- Acceptance: Treat disagreement, stale evidence, unsupported claims, and expected negative-control counterexamples as non-secure outcomes.

## PORTAL-CXTP-134 Generate Testnet Apalache concurrency model

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the Testnet TLA artifact, report, documentation, and test.
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-131
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/tla/XamanTestnetPayload.tla, security_ir_artifacts/corpora/xaman-app/testnet/tla/apalache-report.json, docs/security_verification/xaman_testnet_apalache.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_apalache.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_apalache.py -q
- Acceptance: Bound concurrency claims to the reviewed state machine and reject missing solver output or unmodeled state as assurance evidence.

## PORTAL-CXTP-135 Generate Testnet Tamarin/ProVerif protocol model

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the protocol artifact, report, documentation, and test.
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-131
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/protocol/xaman_testnet_payload.spthy, security_ir_artifacts/corpora/xaman-app/testnet/protocol/protocol-report.json, docs/security_verification/xaman_testnet_protocol_verification.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_protocol.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_protocol.py -q
- Acceptance: Restrict protocol conclusions to the symbolic model and report replay, secret, authentication, or backend gaps explicitly.

## PORTAL-CXTP-136 Check Lean kernel and decide independent Rocq coverage

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the Lean kernel, report, Rocq coverage decision, and documentation.
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-131
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.lean, security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/lean-report.json, security_ir_artifacts/corpora/xaman-app/testnet/coq-coverage-decision.json, docs/security_verification/xaman_testnet_kernel_proofs.md
- Validation: test -f security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/lean-report.json
- Acceptance: Accept only kernel-checked modeled invariants and preserve independent-kernel requirements as coverage gates.

## PORTAL-CXTP-137 Govern Leanstral-assisted proof suggestions

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the Leanstral lock, candidate audit, and policy document.
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-136
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/leanstral-assistant-lock.json, security_ir_artifacts/corpora/xaman-app/testnet/leanstral-candidate-audit.json, docs/security_verification/xaman_testnet_leanstral_policy.md
- Validation: test -f security_ir_artifacts/corpora/xaman-app/testnet/leanstral-candidate-audit.json
- Acceptance: Treat Leanstral output as untrusted suggestions until Lean, Rocq, or another independent checker accepts the resulting artifact.

## PORTAL-CXTP-138 Execute Testnet fuzzing and counterexample retention

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the fuzz report, counterexample directory, documentation, and test.
- Priority: P0
- Track: disproof
- Depends on: PORTAL-CXTP-131
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json, security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/, docs/security_verification/xaman_testnet_fuzzing.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_fuzzing.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_fuzzing.py -q
- Acceptance: Retain seeds, registered mutation domains, and minimized counterexamples while never inferring exhaustive real-wallet coverage from bounded fuzzing.

## PORTAL-CXTP-139 Generate fail-closed Testnet assurance verdict

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the assurance bundle, verdict, and documentation.
- Priority: P0
- Track: assurance
- Depends on: PORTAL-CXTP-132, PORTAL-CXTP-133, PORTAL-CXTP-134, PORTAL-CXTP-135, PORTAL-CXTP-136, PORTAL-CXTP-137, PORTAL-CXTP-138
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/assurance-bundle.json, security_ir_artifacts/corpora/xaman-app/testnet/assurance-verdict.json, docs/security_verification/xaman_xrpl_testnet_assurance_verdict.md
- Validation: test -f security_ir_artifacts/corpora/xaman-app/testnet/assurance-verdict.json
- Acceptance: Issue only a scope-bounded result and retain every missing assumption, unmodeled claim, or failed lane as a Testnet assurance block.

## PORTAL-CXTP-140 Reconcile Xaman TLA workflow with executable Apalache evidence

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the reconciled TLA workflow, Apalache lane report, and tests.
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-071, PORTAL-CXTP-134
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/reports/xaman_tla_workflow.py, scripts/ops/security_verification/generate_xaman_tla_workflow.py, security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla, security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json, security_ir_artifacts/environment/apalache-solver-lane-report.json, docs/security_verification/xaman_tla_workflow.md, docs/security_verification/apalache_tla_solver_lane.md, tests/logic/security_models/crypto_exchange/test_xaman_tla_workflow.py, tests/logic/security_models/crypto_exchange/test_apalache_solver_lane.py
- Validation: PATH=/home/barberb/.local/bin:$PATH PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_tla_workflow.py tests/logic/security_models/crypto_exchange/test_apalache_solver_lane.py -q
- Acceptance: Bind bounded Apalache results to generated source, exact solver evidence, and the stated non-production scope.

## PORTAL-CXTP-141 Pin a Tamarin-supported Maude runtime

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the Tamarin/Maude runtime probe report, documentation, and test.
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-092
- Outputs: scripts/ops/security_verification/probe_tamarin_runtime.py, security_ir_artifacts/environment/tamarin-runtime-report.json, docs/security_verification/xaman_tamarin_runtime.md, tests/logic/security_models/crypto_exchange/test_tamarin_runtime.py
- Validation: PATH=/home/barberb/.local/bin:$PATH PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_tamarin_runtime.py -q
- Acceptance: Pin and verify a Maude release accepted by Tamarin, preserving unsupported protocol models as coverage gaps.

## PORTAL-CXTP-142 Finalize headless ProVerif and Rocq proof toolchain evidence

- Status: completed
- Completion: manual
- Completion evidence: Completed supervisor state retains the headless ProVerif/Rocq toolchain probe, documentation, and test.
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-093
- Outputs: scripts/ops/security_verification/probe_opam_proof_toolchain.py, security_ir_artifacts/environment/opam-proof-toolchain-report.json, docs/security_verification/xaman_opam_proof_toolchain.md, tests/logic/security_models/crypto_exchange/test_opam_proof_toolchain.py
- Validation: PATH=/home/barberb/.local/bin:$PATH PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_opam_proof_toolchain.py -q
- Acceptance: Retain a headless ProVerif and Rocq/Coq proof-toolchain record with versions, paths, and fail-closed lane semantics.

## Xaman Public-Source And XRPL Testnet Execution Extension

Target corpus: `XRPL-Labs/Xaman-App` at the manifest-pinned commit. The corpus is
a React Native mobile XRP Ledger client with a remote sign-request platform
boundary. The proof target is therefore a public-source/Testnet property under
declared assumptions, never a blanket claim that Xaman, XRPL, or an exchange is
secure. Every unsupported source path, unavailable runtime trace, solver
disagreement, timeout, stale input, or missing reviewer remains `UNKNOWN`,
`NOT_MODELED`, or `BLOCKED`.

Execution sequence:

1. Reconcile the canonical board with supervisor state before scheduling more work.
2. Re-freeze source and public build inputs, then map native bridges, payload APIs,
   deep links, wallet-auth transitions, and XRPL transaction classes to claims.
3. Extend the SecurityModelIR for reachable `TrustSet`, `OfferCreate`, and
   `SignerListSet` paths; preserve unsupported semantics as counterexamples or
   coverage gaps.
4. Run the same immutable model through Z3/CVC5, Apalache, Tamarin/ProVerif,
   Lean, and Rocq only where each solver's theory is appropriate. Leanstral may
   propose artifacts but no generated result is accepted without an independent
   checker.
5. Fuzz and mutate the modeled boundary, collect redacted Testnet-only runtime
   evidence, and make the assurance verdict reject all unmodeled or unreviewed
   conditions.
6. Keep vendor-only requirements (released APK provenance, native vault and
   biometric behavior, backend single-use semantics, and XRPL/RPC trust) blocked
   until authorized evidence and accountable review exist.

## PORTAL-CXTP-143 Reconcile canonical CXTP taskboard with supervisor state

- Status: completed
- Completion: manual
- Priority: P0
- Track: ops
- Depends on:
- Outputs: docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md, security_ir_artifacts/recovery/cxtp-taskboard-state-reconciliation.json, docs/security_verification/cxtp_taskboard_state_reconciliation.md, tests/logic/security_models/crypto_exchange/test_cxtp_taskboard_state_reconciliation.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_cxtp_taskboard_state_reconciliation.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/preflight_crypto_exchange_taskboard.py --out security_ir_artifacts/recovery/taskboard-preflight-report.json
- Acceptance: Reconstruct durable task records for every supervisor state task absent from the canonical board, preserve completed evidence for PORTAL-CXTP-119 through PORTAL-CXTP-142, make task counts and statuses agree, reject unknown state IDs, and leave at least one valid next task selectable without downgrading any production blocker.

## PORTAL-CXTP-144 Refresh the pinned Xaman public-source and Testnet assessment baseline

- Status: completed
- Completion: manual
- Priority: P0
- Track: source
- Depends on: PORTAL-CXTP-143
- Outputs: security_ir_artifacts/corpora/xaman-app/public-source-refresh.json, security_ir_artifacts/corpora/xaman-app/public-source-assessment.json, docs/security_verification/xaman_public_source_security_verification_plan.md, tests/logic/security_models/crypto_exchange/test_xaman_public_source_refresh.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_public_source_refresh.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/build_xaman_public_source_assessment.py --out security_ir_artifacts/corpora/xaman-app/public-source-assessment.json
- Acceptance: Revalidate the exact source commit, repository URL, lockfile and public-build digests, responsible-disclosure path, source coverage, known unmodeled domains, and Testnet-only scope; record upstream drift without silently changing the proof corpus.

## PORTAL-CXTP-145 Build a claim-to-source map for wallet, payload, native bridge, and deep-link boundaries

- Status: completed
- Completion: manual
- Priority: P0
- Track: model
- Depends on: PORTAL-CXTP-143, PORTAL-CXTP-144
- Outputs: security_ir_artifacts/corpora/xaman-app/source-claim-map.json, security_ir_artifacts/corpora/xaman-app/native-boundary-coverage.json, docs/security_verification/xaman_source_claim_coverage.md, tests/logic/security_models/crypto_exchange/test_xaman_source_claim_coverage.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_source_claim_coverage.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/build_xaman_source_claim_coverage.py --out security_ir_artifacts/corpora/xaman-app/source-claim-map.json
- Acceptance: Bind every modeled wallet-auth, payload review, signing decision, deep-link, QR, network-selection, receipt-consumer, and native-bridge claim to immutable public-source locations; mark vault cryptography, biometrics, native keystore behavior, and backend behavior as `NOT_MODELED` unless source-supported evidence exists.

## PORTAL-CXTP-146 Extend XRPL transaction semantics for reachable public Xaman flows

- Status: completed
- Completion: manual
- Priority: P0
- Track: model
- Depends on: PORTAL-CXTP-143, PORTAL-CXTP-144
- Outputs: security_ir_artifacts/corpora/xaman-app/xrpl-transaction-coverage.json, security_ir_artifacts/corpora/xaman-app/disproof-vectors.json, docs/security_verification/xaman_xrpl_transaction_model.md, tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_coverage.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_coverage.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/generate_xaman_disproof_vectors.py --out security_ir_artifacts/corpora/xaman-app/disproof-vectors.json
- Acceptance: Model or explicitly reject reachable `TrustSet`, `OfferCreate`, `SignerListSet`, payment, issued-currency, destination-tag, fee, sequence, multisign, memo, network, and canonicalization constraints; unsupported transaction types must yield a recorded coverage gap or counterexample, never a proof.

## PORTAL-CXTP-147 Run a reconciled multi-solver public-source Testnet proof portfolio

- Status: completed
- Completion: manual
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-143, PORTAL-CXTP-145, PORTAL-CXTP-146
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-manifest.json, security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-report.json, docs/security_verification/xaman_testnet_solver_portfolio.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_solver_portfolio.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_solver_portfolio.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/run_xaman_testnet_solver_portfolio.py --out security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-report.json
- Acceptance: Record one frozen model CID and evidence digest set per claim, then run Z3/CVC5 differential checks, Apalache state checks, Tamarin/ProVerif protocol checks, Lean/Rocq kernel checks, and fuzz-result consumption only when the claim fits the solver theory; require recorded executable versions, command digests, timeouts, reviewer status, and a fail-closed result for every unavailable or disagreeing lane.

## PORTAL-CXTP-148 Expand adversarial Testnet fuzzing and formal counterexample minimization

- Status: completed
- Completion: manual
- Priority: P0
- Track: disproof
- Depends on: PORTAL-CXTP-143, PORTAL-CXTP-145, PORTAL-CXTP-146
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/fuzz/campaign-manifest.json, security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json, docs/security_verification/xaman_testnet_adversarial_fuzzing.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_adversarial_fuzzing.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_adversarial_fuzzing.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/run_xaman_testnet_fuzzing.py --out security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json
- Acceptance: Exercise bounded input spaces for malformed and replayed payloads, wrong network, account-import attempts, stale or downgraded evidence, auth/review bypass, cancellation/expiry/reconnect races, transaction-type mutations, and solver-result tampering; minimize every discovered counterexample and reject unregistered fuzz domains as unmodeled.

## PORTAL-CXTP-149 Reproduce the public Android Testnet verifier build with a locked environment

- Status: waiting
- Completion: manual
- Priority: P1
- Track: runtime
- Depends on: PORTAL-CXTP-143, PORTAL-CXTP-144
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/public-build-reproduction.json, security_ir_artifacts/corpora/xaman-app/testnet/public-build-environment.json, docs/security_verification/xaman_testnet_public_build_reproduction.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_public_build_reproduction.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_public_build_reproduction.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/reproduce_xaman_public_testnet_build.py --out security_ir_artifacts/corpora/xaman-app/testnet/public-build-reproduction.json
- Acceptance: Record the public-source commit, Android/Gradle/Node/Java/SDK environment, dependency resolution, build outcome, verifier-only patches, APK digest, and every missing credential or service dependency; never classify a public build as equivalent to a vendor release.

## PORTAL-CXTP-150 Capture and validate redacted XRPL Testnet lifecycle evidence

- Status: waiting
- Completion: manual
- Priority: P0
- Track: runtime
- Depends on: PORTAL-CXTP-143, PORTAL-CXTP-145, PORTAL-CXTP-147, PORTAL-CXTP-148, PORTAL-CXTP-149
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-report.json, security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-trace-map.json, docs/security_verification/xaman_testnet_runtime_conformance.md, tests/logic/security_models/crypto_exchange/test_xaman_testnet_runtime_conformance.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_runtime_conformance.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/validate_xaman_testnet_runtime_conformance.py --out security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-report.json
- Acceptance: Bind fresh-emulator, Testnet-only network, fresh-account, review, authentication, signing decision, submit attempt/result, cancellation, expiry, replay, reconnect, and network-change categories to the frozen model without retaining seeds, addresses, payloads, transaction blobs, credentials, or raw endpoints; missing paths remain a Testnet assurance block.

## PORTAL-CXTP-151 Issue a bounded Xaman public-source/Testnet assurance verdict

- Status: waiting
- Completion: manual
- Priority: P0
- Track: assurance
- Depends on: PORTAL-CXTP-143, PORTAL-CXTP-147, PORTAL-CXTP-148, PORTAL-CXTP-150
- Outputs: security_ir_artifacts/corpora/xaman-app/testnet/public-source-testnet-assurance-verdict.json, security_ir_artifacts/corpora/xaman-app/testnet/public-source-testnet-assurance-bundle.json, docs/security_verification/xaman_public_source_testnet_assurance_verdict.md, tests/logic/security_models/crypto_exchange/test_xaman_public_source_testnet_assurance_verdict.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_public_source_testnet_assurance_verdict.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/generate_xaman_public_source_testnet_assurance_verdict.py --out security_ir_artifacts/corpora/xaman-app/testnet/public-source-testnet-assurance-verdict.json
- Acceptance: Emit only `TESTNET_SCOPE_ASSURED`, `DISPROVED`, `UNKNOWN`, `NOT_MODELED`, or `BLOCKED`; accept `TESTNET_SCOPE_ASSURED` only when every required claim has current reviewed source/runtime evidence and required solver results, and state prominently that it is not a production or vendor-release security decision.

## PORTAL-CXTP-152 Prepare an authorized vendor-evidence intake request for native and backend blockers

- Status: waiting
- Completion: manual
- Priority: P1
- Track: governance
- Depends on: PORTAL-CXTP-143, PORTAL-CXTP-145
- Outputs: docs/security_verification/xaman_vendor_evidence_request.md, security_ir_artifacts/corpora/xaman-app/vendor-evidence-intake-template.json, tests/logic/security_models/crypto_exchange/test_xaman_vendor_evidence_request.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_vendor_evidence_request.py -q
- Acceptance: Define redacted, authorized requests for release provenance, native vault/biometric policy, backend payload single-use/conflict/expiry semantics, signed-build attestation, test-device trace review, XRPL/RPC trust assumptions, responsible-disclosure routing, accountable owners, expiry, and review criteria; this task must not claim access to or truth of vendor-only evidence.

## PORTAL-CXTP-153 Collect vendor-authorized native, backend, and XRPL trust evidence

- Status: blocked
- Completion: manual
- Priority: P0
- Track: governance
- Blocked reason: Requires XRPL Labs-authorized release provenance, native vault and biometric documentation, backend payload-service evidence, XRPL/RPC trust assumptions, accountable owners, and responsible-disclosure approval.
- Depends on: PORTAL-CXTP-152
- Outputs: security_ir_artifacts/corpora/xaman-app/vendor-evidence-manifest.json, security_ir_artifacts/corpora/xaman-app/vendor-evidence-review.json, docs/security_verification/xaman_vendor_evidence_review.md
- Validation: test -f security_ir_artifacts/corpora/xaman-app/vendor-evidence-manifest.json; test -f security_ir_artifacts/corpora/xaman-app/vendor-evidence-review.json; test -f docs/security_verification/xaman_vendor_evidence_review.md
- Acceptance: Permit vendor-release assurance work only after authorized, redacted, current, reviewed evidence binds every native, backend, build, and XRPL/RPC assumption to an accountable owner; otherwise preserve the public-source/Testnet non-secure boundary.
