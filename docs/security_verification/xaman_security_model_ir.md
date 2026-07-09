# Xaman SecurityModelIR Baseline

Task: `PORTAL-CXTP-068`

The canonical SecurityModelIR artifact is
`security_ir_artifacts/corpora/xaman-app/security-model-ir.json`. Its
deterministic content address is stored in
`security_ir_artifacts/corpora/xaman-app/security-model-ir.cid`.

## Source Binding

- Corpus: `xaman-app`
- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest aggregate SHA-256: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`
- Environment probe: `security_ir_artifacts/corpora/xaman-app/environment-probe.json`
- Environment decision: `XAMAN_ENVIRONMENT_READY_WITH_CAPABILITY_GAPS`
- Canonical model CID: `bafkreicugppxuacf5kxjsor7lqhwa3y44rrbsetiid2e65utlwgyablr5e`

## Dependency Inputs

| Artifact | Schema | Task |
| --- | --- | --- |
| `security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json` | `xaman-wallet-auth-facts/v1` | `PORTAL-CXTP-064` |
| `security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json` | `xaman-payload-lifecycle-facts/v1` | `PORTAL-CXTP-065` |
| `security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json` | `xaman-xrpl-transaction-facts/v1` | `PORTAL-CXTP-066` |
| `security_ir_artifacts/corpora/xaman-app/security-claims.json` | `xaman-security-claims/v1` | `PORTAL-CXTP-067` |

The IR binds 71
reviewed source facts and 14
explicit `NOT_MODELED` gaps from the wallet-auth, payload-lifecycle, and XRPL
transaction artifacts.

## Claim Projection

| Xaman category | IR domain | Gate | Source status | Claim |
| --- | --- | --- | --- | --- |
| `custody` | `vault` | `blocking` | `BLOCKED_BY_ASSUMPTIONS` | `xaman-security:claim:custody-software-private-key-not-available-without-authorized-vault-path` |
| `authentication` | `auth_component` | `blocking` | `BLOCKED_BY_ASSUMPTIONS` | `xaman-security:claim:authentication-gates-vault-and-signing` |
| `payload_integrity` | `payload` | `high` | `BLOCKED_BY_ASSUMPTIONS` | `xaman-security:claim:payload-integrity-before-review-and-signing` |
| `replay_prevention` | `payload` | `blocking` | `BLOCKED_BY_ASSUMPTIONS` | `xaman-security:claim:payload-replay-prevention-is-single-use` |
| `network_binding` | `ledger` | `high` | `BLOCKED_BY_ASSUMPTIONS` | `xaman-security:claim:network-binding-prevents-cross-network-signing` |
| `transaction_semantics` | `ledger` | `high` | `BLOCKED_BY_ASSUMPTIONS` | `xaman-security:claim:xrpl-transaction-semantics-match-reviewed-signing-intent` |
| `backend_trust` | `service` | `blocking` | `BLOCKED_BY_ASSUMPTIONS` | `xaman-security:claim:backend-trust-boundary-is-safe-for-payload-resolution` |
| `runtime_equivalence` | `e2e_flow` | `blocking` | `BLOCKED_BY_ASSUMPTIONS` | `xaman-security:claim:reviewed-source-is-equivalent-to-deployed-runtime` |
| `proof_consumer_policy` | `service` | `blocking` | `BLOCKED_BY_ASSUMPTIONS` | `xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims` |

Domain coverage in the baseline:

| IR domain | Claim count |
| --- | ---: |
| `auth_component` | 1 |
| `e2e_flow` | 1 |
| `ledger` | 2 |
| `payload` | 2 |
| `service` | 2 |
| `vault` | 1 |

## Assumptions And Blocking State

The model carries 20 Xaman assumptions from
`security-claims.json`. 12 assumptions remain
`BLOCKING`; therefore every proof obligation is emitted with status
`NOT_MODELED` and every solver result is `not-modeled` until the missing
evidence is supplied and reviewed.

Blocking assumptions are not erased by the IR. They remain attached to claims,
proof obligations, disproof vectors, and metadata so proof consumers can fail
closed instead of accepting a partial model.

## Solver Obligations And Disproof Vectors

- Proof obligations: 18 (`z3` and `cvc5` for each Xaman claim)
- Solver results: 18 baseline `not-modeled` entries
- Disproof vectors: 9 mutation, bypass, replay, substitution, and consumer-policy vectors
- Runtime trace projections: 9

The next solver task can compile these obligations to SMT-LIB without needing
to rediscover the source commit, environment profile, reviewed fact IDs,
assumption IDs, or disproof tactics.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_model_ir.py -q
```

The tests validate schema conformance, dependency bindings, claim and
assumption closure, proof and disproof coverage, canonical JSON stability, and
CID sidecar recomputation.
