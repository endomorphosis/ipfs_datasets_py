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

- Status: todo
- Completion: manual
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

- Status: todo
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-057, PORTAL-CXTP-059
- Outputs: docs/security_verification/xaman_corpus_profile.md, security_ir_artifacts/corpora/xaman-app/source-manifest.json, scripts/ops/security_verification/fetch_xaman_corpus.py, tests/logic/security_models/crypto_exchange/test_xaman_corpus_manifest.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_corpus_manifest.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/fetch_xaman_corpus.py --repo https://github.com/XRPL-Labs/Xaman-App --ref 942f43876265a7af44f233288ad2b1d00841d5fa --out security_ir_artifacts/corpora/xaman-app/source-manifest.json
- Acceptance: Fetch or reference the Xaman-App corpus at the exact pinned commit, record source URL, commit SHA, sparse checkout paths, file digests, dependency lockfiles, license and security-disclosure files, and fail closed if the corpus cannot be reproduced.

## PORTAL-CXTP-061 Build Xaman dependency and build-environment probe

- Status: todo
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-060, PORTAL-CXTP-089
- Outputs: docs/security_verification/xaman_environment_assumptions.md, scripts/ops/security_verification/probe_xaman_environment.py, security_ir_artifacts/corpora/xaman-app/environment-probe.json, tests/logic/security_models/crypto_exchange/test_xaman_environment_probe.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_environment_probe.py -q; PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_xaman_environment.py --corpus-manifest security_ir_artifacts/corpora/xaman-app/source-manifest.json --out security_ir_artifacts/corpora/xaman-app/environment-probe.json
- Acceptance: Record Node and npm requirements, React Native build assumptions, iOS and Android native assumptions, dependency lockfile digest, TypeScript config, Detox or e2e availability, solver paths, and missing dependency blockers.

## PORTAL-CXTP-062 Restore SecurityModelIR schema and source coverage gates

- Status: todo
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: PORTAL-CXTP-056, PORTAL-CXTP-059, PORTAL-CXTP-088
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/ir/schema.py, ipfs_datasets_py/logic/security_models/crypto_exchange/ir/canonicalize.py, docs/security_verification/code_to_ir_evidence_matrix.md, tests/logic/security_models/crypto_exchange/test_ir_schema.py, tests/logic/security_models/crypto_exchange/test_code_to_ir_coverage.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_ir_schema.py tests/logic/security_models/crypto_exchange/test_code_to_ir_coverage.py -q
- Acceptance: Restore a typed IR with assumptions, evidence, claims, proof obligations, disproof vectors, runtime traces, solver results, CIDs, and fail-closed coverage checks for every production and Xaman security domain.

## PORTAL-CXTP-063 Extend extractor for Xaman React Native TypeScript corpus

- Status: todo
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: PORTAL-CXTP-060, PORTAL-CXTP-062
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/extractors/xaman_source_extractor.py, security_ir_artifacts/corpora/xaman-app/source-coverage.json, tests/logic/security_models/crypto_exchange/test_xaman_source_extractor.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_source_extractor.py -q
- Acceptance: Parse Xaman path aliases and TypeScript or TSX files, classify security-relevant modules in services, store, payload, ledger, vault, auth UI, and e2e flows, and emit reviewed coverage gaps instead of silently ignoring unsupported files.

## PORTAL-CXTP-064 Model Xaman account, vault, storage, and authentication facts

- Status: todo
- Completion: manual
- Priority: P0
- Track: wallet
- Depends on: PORTAL-CXTP-060, PORTAL-CXTP-063
- Outputs: docs/security_verification/xaman_wallet_auth_model.md, security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json, tests/logic/security_models/crypto_exchange/test_xaman_wallet_auth_model.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_wallet_auth_model.py -q
- Acceptance: Extract reviewed facts for account storage, vault access, authentication overlays, biometric or passcode gates, key custody boundaries, signing preconditions, and unsupported source gaps marked `NOT_MODELED`.

## PORTAL-CXTP-065 Model Xaman payload and sign-request lifecycle

- Status: todo
- Completion: manual
- Priority: P0
- Track: wallet
- Depends on: PORTAL-CXTP-060, PORTAL-CXTP-063
- Outputs: docs/security_verification/xaman_payload_lifecycle_model.md, security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json, tests/logic/security_models/crypto_exchange/test_xaman_payload_lifecycle.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_payload_lifecycle.py -q
- Acceptance: Model payload creation, QR and deep-link intake, review UI, approval, rejection, expiration, replay controls, network binding, signing, backend patching, and broadcast boundaries with source evidence.

## PORTAL-CXTP-066 Model XRPL transaction semantics from Xaman ledger code

- Status: todo
- Completion: manual
- Priority: P0
- Track: ledger
- Depends on: PORTAL-CXTP-060, PORTAL-CXTP-063
- Outputs: docs/security_verification/xaman_xrpl_transaction_model.md, security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json, tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_model.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_model.py -q
- Acceptance: Model account, destination, amount, fee, sequence, network, memo, issued-currency, trustline, multisign, and transaction-type constraints needed for XRPL signing safety claims.

## PORTAL-CXTP-067 Define Xaman XRPL security claims and assumptions

- Status: todo
- Completion: manual
- Priority: P0
- Track: wallet
- Depends on: PORTAL-CXTP-064, PORTAL-CXTP-065, PORTAL-CXTP-066
- Outputs: docs/security_verification/xaman_security_claims.md, security_ir_artifacts/corpora/xaman-app/security-claims.json, tests/logic/security_models/crypto_exchange/test_xaman_security_claims.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_claims.py -q
- Acceptance: Define blocking and high-risk claims for custody, authentication, payload integrity, replay prevention, network binding, transaction semantics, backend trust, runtime equivalence, and proof-consumer policy, with every assumption explicitly evidenced or marked blocking.

## PORTAL-CXTP-068 Generate Xaman SecurityModelIR baseline

- Status: todo
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: PORTAL-CXTP-062, PORTAL-CXTP-067
- Outputs: security_ir_artifacts/corpora/xaman-app/security-model-ir.json, security_ir_artifacts/corpora/xaman-app/security-model-ir.cid, docs/security_verification/xaman_security_model_ir.md, tests/logic/security_models/crypto_exchange/test_xaman_security_model_ir.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_model_ir.py -q
- Acceptance: Build a canonical IR that binds corpus commit, environment probe, reviewed source facts, assumptions, claims, solver obligations, disproof vectors, and deterministic CID output.

## PORTAL-CXTP-069 Emit SMT-LIB and run Z3/CVC5 differential proofs

- Status: todo
- Completion: manual
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-068, PORTAL-CXTP-089
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/compilers/to_smtlib.py, ipfs_datasets_py/logic/security_models/crypto_exchange/runners/cvc5_runner.py, security_ir_artifacts/corpora/xaman-app/smtlib/manifest.json, security_ir_artifacts/corpora/xaman-app/proof-reports/z3-cvc5-differential.json, tests/logic/security_models/crypto_exchange/test_xaman_smt_differential.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_smt_differential.py -q
- Acceptance: Cross-check all blocking and high Xaman claims with Z3 and CVC5, attach SMT-LIB artifacts, reject unsupported theories and disagreements, and classify every result as proved, disproved, unknown, or blocked.

## PORTAL-CXTP-070 Build mutation and disproof counterexample suite

- Status: todo
- Completion: manual
- Priority: P0
- Track: solver
- Depends on: PORTAL-CXTP-067, PORTAL-CXTP-068
- Outputs: security_ir_artifacts/corpora/xaman-app/disproof-vectors.json, security_ir_artifacts/corpora/xaman-app/counterexample-report.json, tests/logic/security_models/crypto_exchange/test_xaman_disproof_vectors.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_disproof_vectors.py -q
- Acceptance: Mutate assumptions, remove auth preconditions, stale evidence, wrong network, replay payloads, downgraded solvers, unsupported XRPL semantics, and backend trust failures, and verify that expected counterexamples are found or explicitly blocked.

## PORTAL-CXTP-071 Add TLA/Apalache workflow checks for Xaman signing

- Status: todo
- Completion: manual
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-065, PORTAL-CXTP-067, PORTAL-CXTP-086
- Outputs: security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla, security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json, docs/security_verification/xaman_tla_workflow.md, tests/logic/security_models/crypto_exchange/test_xaman_tla_workflow.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_tla_workflow.py -q
- Acceptance: Check temporal properties for fetch, review, approval, revalidation, signing, rejection, expiration, replay, network binding, and broadcast transitions, and mark Apalache absence as a solver blocker.

## PORTAL-CXTP-072 Add Tamarin/ProVerif protocol checks for payload flow

- Status: todo
- Completion: manual
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-065, PORTAL-CXTP-067, PORTAL-CXTP-086
- Outputs: security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy, security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json, docs/security_verification/xaman_protocol_model.md, tests/logic/security_models/crypto_exchange/test_xaman_protocol_projection.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_protocol_projection.py -q
- Acceptance: Model payload session identities, requester binding, QR/deep-link intake, replay, secrets, signatures, and backend trust boundaries, and reject claims that require unavailable protocol evidence.

## PORTAL-CXTP-073 Add Lean/Coq proof-consumer invariants

- Status: todo
- Completion: manual
- Priority: P1
- Track: solver
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-067, PORTAL-CXTP-086
- Outputs: security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean, security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json, docs/security_verification/xaman_proof_consumer_invariants.md, tests/logic/security_models/crypto_exchange/test_xaman_proof_consumer_invariants.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_proof_consumer_invariants.py -q
- Acceptance: Prove or check that accepted proof receipts bind model CID, claim ID, report CID, solver identity, assumptions, reviewed source evidence, corpus commit, and fresh environment probe, and cannot accept disproved, unknown, not-modeled, stale, or missing-solver outcomes.

## PORTAL-CXTP-074 Ingest Xaman e2e and runtime traces

- Status: todo
- Completion: manual
- Priority: P1
- Track: runtime
- Depends on: PORTAL-CXTP-061, PORTAL-CXTP-065, PORTAL-CXTP-066
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/extractors/xaman_runtime_trace_ingestor.py, security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json, docs/security_verification/xaman_runtime_trace_assumptions.md, tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py -q
- Acceptance: Convert e2e and runtime events into monitor facts for payload intake, review, auth, signing, rejection, expiration, network binding, and broadcast, while marking absent real-device traces as blocking runtime-equivalence evidence.

## PORTAL-CXTP-075 Produce Xaman assurance packet and release decision

- Status: todo
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-069, PORTAL-CXTP-070, PORTAL-CXTP-071, PORTAL-CXTP-072, PORTAL-CXTP-073, PORTAL-CXTP-074
- Outputs: security_ir_artifacts/corpora/xaman-app/assurance-packet.json, docs/security_verification/xaman_assurance_packet.md, docs/security_verification/xaman_release_decision.md, tests/logic/security_models/crypto_exchange/test_xaman_assurance_packet.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_assurance_packet.py -q
- Acceptance: Bundle model CID, corpus commit, manifest, environment probe, proof reports, disproof reports, solver matrix, runtime traces, open blockers, assumptions, and a fail-closed release decision.

## PORTAL-CXTP-076 Bridge Xaman artifacts into production-blocker removal

- Status: todo
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

- Status: todo
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-056, PORTAL-CXTP-059, PORTAL-CXTP-088
- Outputs: docs/security_verification/production_evidence_intake.md, scripts/ops/security_verification/validate_production_evidence_bundle.py, security_ir_artifacts/production/evidence-bundle.schema.json, tests/logic/security_models/crypto_exchange/test_production_evidence_intake.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_evidence_intake.py -q
- Acceptance: Create an intake schema and validator for production source snapshots, environment evidence, runtime traces, owner signoff, solver reports, and freshness metadata so blocked production tasks can be unblocked by a concrete bundle.

## PORTAL-CXTP-086 Build optional solver installer and blocker remover

- Status: todo
- Completion: manual
- Priority: P1
- Track: ops
- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-088
- Outputs: docs/security_verification/optional_solver_installation.md, scripts/ops/security_verification/install_optional_theorem_solvers.py, security_ir_artifacts/environment/optional-solver-install-report.json, tests/logic/security_models/crypto_exchange/test_optional_solver_installer.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_optional_solver_installer.py -q
- Acceptance: Provide safe install/probe commands for Apalache, Tamarin, ProVerif, Lean, and Coq, record unsupported platforms, and convert missing optional solvers into explicit blocked or degraded proof lanes rather than silent success.

## PORTAL-CXTP-087 Wire taskboard integrity into CI and supervisor preflight

- Status: todo
- Completion: manual
- Priority: P1
- Track: quality
- Depends on: PORTAL-CXTP-057, PORTAL-CXTP-088
- Outputs: .github/workflows/crypto-exchange-security-verification.yml, scripts/ops/security_verification/preflight_crypto_exchange_taskboard.py, docs/security_verification/taskboard_preflight_ci.md, tests/logic/security_models/crypto_exchange/test_taskboard_preflight.py
- Validation: PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_taskboard_preflight.py -q
- Acceptance: Make CI and supervisor preflight fail when the taskboard has no parseable tasks, source files disappear, required artifacts are absent, statuses contradict evidence, or production blockers are accidentally treated as release-acceptable.
