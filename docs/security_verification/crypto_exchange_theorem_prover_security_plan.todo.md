# Crypto Exchange Theorem-Prover Security Plan

Date: 2026-07-07

Scope: `ipfs_datasets_py/logic/security_models/crypto_exchange`, the wallet and cryptocurrency exchange model that feeds theorem-prover-backed proof, disproof, receipt, and runtime-monitoring artifacts.

This plan turns the current bounded verifier into an assurance workflow that can either support a release decision or produce concrete counterexamples, `UNKNOWN`, or `NOT_MODELED` results that block the claim that the wallet/exchange system is secure.

## Executive Position

The current code can prove and disprove properties of a canonical `SecurityModelIR` using the implemented Z3 backend. It already produces proof reports, disproof reports, proof receipts, assumption-registry summaries, release-gate results, and a Markdown assurance baseline.

That does not prove the production wallet/exchange system secure by itself. A production security conclusion is only defensible when the IR is complete, reviewed, tied to deployed code and environment facts, and checked by fail-closed proof and disproof gates.

The strongest defensible outcome should be phrased as:

- `release accepted`: all blocking and high-risk modeled claims are proved under owned, current, accepted assumptions, and disproof scenarios still fail as expected.
- `release rejected`: at least one blocking/high claim is `DISPROVED`, `UNKNOWN`, `NOT_MODELED`, missing required assumptions, backed only by unreviewed evidence, or contradicted by runtime traces.
- `inconclusive`: the proof boundary is incomplete, the environment profile is missing, or required prover/runtime evidence cannot be produced.

## Existing Verification Surface

Implemented and usable now:

- Canonical `SecurityModelIR` with content-addressed model artifacts.
- Z3-backed proof runner for wallet/exchange claims.
- Release policy that gates blocking, high, and medium claims.
- Assumption registry for ownership, evidence, review, and freshness.
- Source autoformalization for Python, JavaScript, TypeScript, Go, Java, and Rust seed facts.
- OpenAPI, log trace, UCAN policy, and feature-loop projection helpers.
- Deterministic disproof and bounded mutation suite.
- Proof report, counterexample report, and proof receipt emitters.
- Runtime temporal monitor for event dictionaries.
- TypeScript/WASM-facing schema emission for proof consumers.
- Fail-closed assurance baseline runner.

Planning targets, not current proof authority:

- CVC5 differential SMT backend.
- TLA+/Apalache state-machine checking.
- Tamarin or ProVerif protocol proofs.
- Lean or Coq proof-consumer invariant checking.
- HyperLTL or equivalent hyperproperty checks.

## Soundness Boundary

`PROVED` means the implemented backend established the selected property over the selected finite IR under the listed assumptions. It does not mean the entire production exchange, all operational procedures, all dependencies, all chains, or all future traces are secure.

The proof boundary must fail closed:

- Treat `DISPROVED` as a concrete security failure for the relevant claim.
- Treat blocking/high `UNKNOWN` as not secure.
- Treat blocking/high `NOT_MODELED` as not secure.
- Treat stale, ownerless, unevidenced, or unaccepted assumptions as not secure.
- Treat unreviewed heuristic evidence for production-critical facts as not secure.
- Treat missing domains as not secure.
- Treat runtime trace violations as counterexample evidence.

## Security Claims To Gate

The current release policy should remain the first production gate:

- `no_unauthorized_withdrawal`: no withdrawal can be authorized without a valid policy, capability, approval, and signing path.
- `no_over_reserved_internal_account`: reservations cannot exceed available balances under the modeled transaction semantics.
- `global_asset_conservation`: ledger totals preserve asset accounting except for explicitly modeled external movements.
- `no_deposit_before_finality`: deposits are not credited before configured chain and asset finality.
- `no_signing_request_after_wallet_freeze`: frozen wallets cannot create new signing requests.
- `capability_delegation_no_authority_increase`: delegated authority cannot exceed the delegator authority.
- `revoked_capability_no_future_authorization`: revoked capabilities cannot authorize future privileged actions.
- `audit_event_exists_for_critical_transition`: critical transitions have audit evidence.

Production work should not broaden the security conclusion until new claims are implemented as executable prover gates.

## Required Production Inputs

The production proof run needs these inputs before a release decision can be trusted:

- Wallet, account, ledger, withdrawal, deposit, signing, capability, admin, and audit source code.
- API schemas and traces for withdrawal, deposit, signing, admin, and capability endpoints.
- Policy documents for approval, limits, keys, freeze/unfreeze, delegation, revocation, and incident response.
- HSM or key-manager interface contract, attestation model, and key custody runbook.
- Database isolation level, transaction behavior, idempotency, and nonce reservation behavior.
- Chain/asset finality thresholds, reorg handling, RPC provider trust and failure model.
- Audit-log append-only or tamper-evidence mechanism.
- Runtime event stream mapping for monitorable transitions.
- Exact code revision, dependency/prover versions, and deployment environment profile.

## Phase 1: Freeze The Proof Boundary

Define exactly what the theorem provers are allowed to claim. The release statement must distinguish proof of the IR from proof of the whole production system.

Deliverables:

- Production environment profile.
- Explicit assumption registry entries for every consumed assumption.
- Required domain list for `withdrawals`, `deposits`, `ledger`, `capabilities`, `hsm`, and `audit`.
- Release wording for accepted, rejected, and inconclusive outcomes.

## Phase 2: Build The Production SecurityModelIR

Use autoformalization only as a seed. It is evidence discovery, not proof authority.

Example seed command from `external/ipfs_datasets`:

```bash
PYTHONPATH=. python scripts/ops/security_verification/autoformalize_security_ir.py \
  /path/to/wallet-exchange/source \
  --model-id production-wallet-exchange \
  --out security_ir_artifacts/production/production-security-model.json
```

Then manually review the generated facts:

- Replace heuristic facts with human-reviewed evidence for blocking and high-risk claims.
- Attach source file, line span, digest, API trace, policy document, or operational evidence to each critical fact.
- Remove facts that cannot be tied to deployed code or current policy.
- Keep the model canonical and content-addressed so proof reports bind to one exact payload.

## Phase 3: Run The Fail-Closed Proof Gate

Run the implemented proof gate against the production model.

Example command from `external/ipfs_datasets`:

```bash
PYTHONPATH=. python -m ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all \
  --model security_ir_artifacts/production/production-security-model.json \
  --out security_ir_artifacts/production/proof-report.json \
  --strict-validation \
  --release-gate \
  --require-current-assumptions \
  --require-reviewed-evidence \
  --require-domain withdrawals \
  --require-domain deposits \
  --require-domain ledger \
  --require-domain capabilities \
  --require-domain hsm \
  --require-domain audit \
  --min-modeled-blocking-claims 3 \
  --min-proved-blocking-claims 3 \
  --emit-counterexamples-dir security_ir_artifacts/production/counterexamples \
  --emit-proof-receipts \
  --explain-soundness
```

If this exits non-zero, the release is not formally accepted.

## Phase 4: Run The Disproof Gate

Proofs without counterexample pressure are too weak for this domain. Run deterministic disproof tactics and bounded mutation fuzzing.

Example command from `external/ipfs_datasets`:

```bash
PYTHONPATH=. python scripts/ops/security_verification/run_security_ir_disproof_suite.py \
  --model security_ir_artifacts/production/production-security-model.json \
  --out security_ir_artifacts/production/disproof-report.json \
  --fuzz-rounds 64 \
  --seed 7
```

Required disproof families:

- Unauthorized withdrawal.
- Double-spend and over-reservation.
- Deposit before finality.
- Post-freeze signing.
- Delegation authority escalation.
- Revocation bypass.
- Missing audit transition.
- Multi-asset conservation drift.
- Multi-chain and reorg rollback drift.
- Nonce reuse and mempool replacement.
- Admin compromise and quorum-threshold weakness.
- Stale, delayed, censored, or inconsistent RPC/oracle evidence.

Every known-bad model must produce an expected `DISPROVED` result. A mutant that still proves is a model weakness or claim weakness, not a success.

## Phase 5: Produce A Release Assurance Baseline

Use the combined baseline runner as the release artifact generator.

Example command from `external/ipfs_datasets`:

```bash
PYTHONPATH=. python scripts/ops/security_verification/run_security_ir_assurance_baseline.py \
  --model security_ir_artifacts/production/production-security-model.json \
  --out-dir security_ir_artifacts/production-baseline \
  --fuzz-rounds 64 \
  --seed 7 \
  --min-modeled-blocking-claims 3 \
  --min-proved-blocking-claims 3
```

The baseline must include:

- Proof report JSON.
- Disproof report JSON.
- Markdown summary.
- Model CID.
- Assumption-registry summary.
- Release-gate summary.
- Prover and dependency versions.
- Environment profile reference.
- Counterexamples and runtime violations, if any.

## Phase 6: Add Independent Prover Backends

Do not claim independent-prover assurance until the backend executes end-to-end and writes reports consumed by the same release gate.

Recommended order:

1. CVC5 for differential SMT checking against Z3.
2. TLA+/Apalache for interleavings in withdrawal, reservation, freeze, and signing workflows.
3. Tamarin or ProVerif for key custody, signing authority, replay, and capability protocols.
4. Lean or Coq for proof receipt, canonicalization, and proof-consumer invariants.
5. HyperLTL or equivalent for noninterference and leakage claims.

Each backend must fail closed on disagreement, timeout, unsupported theory, missing executable, or unsupported critical claim.

## Phase 7: Wire Runtime Evidence

Runtime monitoring should validate that live traces stay inside the modeled temporal envelope.

Required mappings:

- Withdrawal request, approval, reservation, broadcast, cancellation, and settlement.
- Wallet freeze, unfreeze, signing request, HSM decision, and broadcast.
- Deposit observation, confirmation depth, finality, credit, rollback, and reorg.
- Capability creation, delegation, caveat, revocation, reinstatement, expiration, and privileged action.
- Audit event emission for every critical transition.

Clean runtime traces can strengthen evidence. Violating traces become counterexamples.

## Phase 8: Harden Proof Consumers

Downstream TypeScript/WASM consumers should not trust prose summaries. They should validate machine artifacts.

Consumer requirements:

- Validate proof receipt schema.
- Validate model CID and report digest.
- Validate accepted assumptions.
- Reject stale model CIDs.
- Reject unknown or unsupported prover names.
- Reject simulated proof dependencies for production.
- Reject unreviewed blocking/high evidence.
- Verify signature or trusted receipt binding.

## Phase 9: Release Decision Policy

Accept the release only when all of these are true:

- Every blocking and high-risk production claim is `PROVED`.
- No blocking or high-risk claim is `DISPROVED`, `UNKNOWN`, or `NOT_MODELED`.
- Every required proof domain is modeled.
- Every blocking/high proof depends only on accepted, current, owned assumptions.
- Every blocking/high proof is backed by reviewed production evidence.
- Disproof scenarios still produce expected counterexamples.
- Runtime monitors show no live trace violations for the release window.
- Proof reports bind to exact model CID, code revision, prover versions, and environment profile.
- Proof receipts are validated by downstream consumers.

Reject or hold the release when any one of these fails.

## Reference Artifacts

- Implementation package: `ipfs_datasets_py/logic/security_models/crypto_exchange`
- Existing plan: `docs/security_verification/crypto_exchange_verification_plan.md`
- Existing taskboard: `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md`
- Prover matrix: `docs/security_verification/prover_matrix.md`
- Threat model: `docs/security_verification/threat_model.md`
- Security IR spec: `docs/security_verification/security_ir_spec.md`
- Built-in assurance summary: `security_ir_artifacts/assurance-run/assurance-baseline.md`
- Built-in proof baseline: `security_ir_artifacts/assurance-run/proof-baseline.json`
- Built-in disproof baseline: `security_ir_artifacts/assurance-run/disproof-baseline.json`

# Agent Supervisor Tasklist

The following tasks use the `ipfs_accelerate_py` agent supervisor format: each task starts with the default `## PORTAL-` header prefix and uses machine-readable `- Key: value` metadata.

## PORTAL-CXTP-001 Define production environment profile

- Status: blocked
- Completion: manual
- Priority: P0
- Track: wallet
- Blocked reason: Production deployment evidence has not been supplied; scaffold artifacts exist and fail closed until real environment facts are reviewed.
- Depends on:
- Outputs: docs/security_verification/production_environment_profile.md, security_ir_artifacts/production/assumption-evidence.json
- Validation: test -f docs/security_verification/production_environment_profile.md; test -f security_ir_artifacts/production/assumption-evidence.json
- Acceptance: Record database isolation, transaction behavior, nonce reservation, chain finality, HSM contract, audit tamper-evidence, RPC trust bounds, deployed revision, and prover/runtime versions needed for production proof assumptions.

## PORTAL-CXTP-002 Generate reviewed production SecurityModelIR candidate

- Status: todo
- Completion: manual
- Priority: P0
- Track: wallet
- Depends on: PORTAL-CXTP-001
- Outputs: security_ir_artifacts/production/production-security-model.json, security_ir_artifacts/production/model-generation-inputs.md
- Validation: test -f security_ir_artifacts/production/production-security-model.json; PYTHONPATH=. python -m json.tool security_ir_artifacts/production/production-security-model.json >/dev/null
- Acceptance: Generate a canonical production model from deployed wallet/exchange code, API evidence, policy documents, and logs, with model inputs documented and no placeholder source paths left in the artifact.

## PORTAL-CXTP-003 Review proof-critical evidence

- Status: todo
- Completion: manual
- Priority: P0
- Track: quality
- Depends on: PORTAL-CXTP-002
- Outputs: docs/security_verification/production_evidence_review.md, security_ir_artifacts/production/evidence-review.json
- Validation: test -f docs/security_verification/production_evidence_review.md; test -f security_ir_artifacts/production/evidence-review.json
- Acceptance: Promote blocking and high-risk proof evidence to human-reviewed or equivalent trusted status, attach source spans and digests, and quarantine any heuristic-only production-critical fact.

## PORTAL-CXTP-004 Run production fail-closed assurance baseline

- Status: todo
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-001, PORTAL-CXTP-002, PORTAL-CXTP-003
- Outputs: security_ir_artifacts/production-baseline/proof-baseline.json, security_ir_artifacts/production-baseline/disproof-baseline.json, security_ir_artifacts/production-baseline/assurance-baseline.md
- Validation: PYTHONPATH=. python scripts/ops/security_verification/run_security_ir_assurance_baseline.py --model security_ir_artifacts/production/production-security-model.json --out-dir security_ir_artifacts/production-baseline --fuzz-rounds 64 --seed 7 --min-modeled-blocking-claims 3 --min-proved-blocking-claims 3
- Acceptance: Produce a release-gated production assurance baseline that exits zero only when blocking claims, high-risk claims, required assumptions, reviewed evidence, and disproof scenarios all satisfy the fail-closed policy.

## PORTAL-CXTP-005 Expand mutation and disproof coverage

- Status: todo
- Completion: manual
- Priority: P1
- Track: quality
- Depends on: PORTAL-CXTP-004
- Outputs: tests/logic/security_models/crypto_exchange/test_production_disproof_regressions.py, docs/security_verification/test_vectors/production_disproof_cases.md
- Validation: PYTHONPATH=. python scripts/ops/security_verification/run_security_ir_disproof_suite.py --model security_ir_artifacts/production/production-security-model.json --out security_ir_artifacts/production-baseline/disproof-expanded.json --fuzz-rounds 128 --seed 7
- Acceptance: Add multi-asset, multi-chain, reorg, nonce reuse, mempool replacement, admin compromise, quorum, stale RPC, delayed RPC, and censored RPC mutants that produce expected counterexamples.

## PORTAL-CXTP-006 Persist counterexamples as regression vectors

- Status: completed
- Completion: manual
- Priority: P1
- Track: quality
- Depends on: PORTAL-CXTP-005
- Outputs: docs/security_verification/test_vectors/counterexamples, tests/logic/security_models/crypto_exchange/test_counterexample_vectors.py
- Validation: test -d docs/security_verification/test_vectors/counterexamples; PYTHONPATH=. pytest tests/logic/security_models/crypto_exchange/test_counterexample_vectors.py -q
- Acceptance: Store stable counterexample JSON fixtures and add regression tests proving future verifier changes keep rejecting each known-bad model.

## PORTAL-CXTP-007 Wire runtime monitor to production event streams

- Status: todo
- Completion: manual
- Priority: P1
- Track: runtime
- Depends on: PORTAL-CXTP-001, PORTAL-CXTP-002
- Outputs: docs/security_verification/runtime_event_mapping.md, security_ir_artifacts/production/runtime-monitor-baseline.json
- Validation: test -f docs/security_verification/runtime_event_mapping.md; test -f security_ir_artifacts/production/runtime-monitor-baseline.json
- Acceptance: Map withdrawal, deposit, signing, wallet-freeze, capability, and audit events into the runtime monitor schema and store release-window trace results as proof evidence or counterexamples.

## PORTAL-CXTP-008 Add CVC5 differential SMT backend

- Status: completed
- Completion: manual
- Priority: P1
- Track: platform
- Depends on: PORTAL-CXTP-004
- Outputs: ipfs_datasets_py/logic/security_models/crypto_exchange/runners/cvc5_runner.py, tests/logic/security_models/crypto_exchange/test_cvc5_runner.py
- Validation: test -f ipfs_datasets_py/logic/security_models/crypto_exchange/runners/cvc5_runner.py; PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_cvc5_runner.py -q
- Acceptance: Add an executable CVC5 backend or explicit fail-closed unavailable state, compare results with Z3 for current claims, and fail critical claims on disagreement, timeout, or unsupported theory.
- Result: Implemented the explicit fail-closed CVC5 unavailable/unsupported state plus `--require-prover-agreement`; native CVC5 SMT-LIB2 proof discharge remains gated by the independent backend promotion criteria.

## PORTAL-CXTP-009 Add TLA or Apalache workflow checks

- Status: todo
- Completion: manual
- Priority: P2
- Track: platform
- Depends on: PORTAL-CXTP-002, PORTAL-CXTP-005
- Outputs: docs/security_verification/tla_workflow_model.md, security_ir_artifacts/production/tla-apalache-report.json
- Validation: test -f docs/security_verification/tla_workflow_model.md; test -f security_ir_artifacts/production/tla-apalache-report.json
- Acceptance: Encode withdrawal, reservation, freeze, signing, and deposit interleavings and store counterexamples for unsafe concurrent workflow traces.

## PORTAL-CXTP-010 Add Tamarin or ProVerif protocol checks

- Status: todo
- Completion: manual
- Priority: P2
- Track: privacy
- Depends on: PORTAL-CXTP-001, PORTAL-CXTP-002
- Outputs: docs/security_verification/protocol_model.md, security_ir_artifacts/production/protocol-proof-report.json
- Validation: test -f docs/security_verification/protocol_model.md; test -f security_ir_artifacts/production/protocol-proof-report.json
- Acceptance: Model key custody, HSM signing authority, replay resistance, capability delegation, revocation propagation, authentication, and secrecy properties with executable protocol-proof evidence or fail-closed unavailable status.

## PORTAL-CXTP-011 Harden TypeScript and WASM proof receipt consumers

- Status: todo
- Completion: manual
- Priority: P1
- Track: wallet
- Depends on: PORTAL-CXTP-004
- Outputs: security_ir_artifacts/production/security-ir-schema.ts, docs/security_verification/proof_receipt_consumer_policy.md
- Validation: PYTHONPATH=. python scripts/ops/security_verification/emit_security_typescript_schema.py --model security_ir_artifacts/production/production-security-model.json --out security_ir_artifacts/production/security-ir-schema.ts; test -f docs/security_verification/proof_receipt_consumer_policy.md
- Acceptance: Require consumers to validate model CID, report digest, accepted assumptions, prover identity, evidence review status, stale model policy, simulated dependency policy, and trusted receipt binding.

## PORTAL-CXTP-012 Add CI and release-gate wiring

- Status: todo
- Completion: manual
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-004, PORTAL-CXTP-006, PORTAL-CXTP-011
- Outputs: .github/workflows/security-logic-ci.yml, docs/security_verification/release_gate_runbook.md
- Validation: test -f .github/workflows/security-logic-ci.yml; test -f docs/security_verification/release_gate_runbook.md
- Acceptance: Wire proof, disproof, assumption freshness, reviewed evidence, TypeScript schema emission, and receipt validation into CI and document the manual release gate for production wallet/exchange deployments.
