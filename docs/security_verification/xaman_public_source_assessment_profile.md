# Xaman Public-Source Security Assessment Profile

Task: `PORTAL-CXTP-119`

Artifact: `security_ir_artifacts/corpora/xaman-app/public-source-assessment.json`

Builder: `scripts/ops/security_verification/build_xaman_public_source_assessment.py`

## Scope

This profile is a fail-closed assessment of the public Xaman source corpus pinned at commit `942f43876265a7af44f233288ad2b1d00841d5fa`. It organizes what the public corpus can support and what remains conditional, unmodeled, or vendor-only.

It is not a production release approval. The JSON profile records:

- `public_source_result: blocked_public_source_assessment`
- `security_decision: BLOCK_PUBLIC_SOURCE_ASSESSMENT_NOT_RELEASE_APPROVAL`
- `production_release_approval: false`
- `release_decision: not_a_release_decision_public_source_only`

Any public-source-only result labeled as production release approval, release approved, production approved, or accepted secure without vendor evidence is explicitly prohibited.

## Public Source-Supported Facts

The assessment imports reviewed public-source facts from:

- `security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json`
- `security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json`
- `security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json`

The generated profile currently records 54 source-supported facts. These facts can support model construction and reviewer reasoning, but they do not clear native vault behavior, backend service behavior, deployed runtime equivalence, ledger consensus, or unavailable solver lanes.

## Conditional Claims

The profile carries 10 security claims from `security-claims.json`. Every claim remains conditional or blocked because each depends on at least one external assumption, vendor-only evidence item, runtime trace, or proof lane.

Conditional claims cover:

- Software custody and authentication gating.
- Payload integrity and replay controls.
- Network binding and XRPL transaction semantics.
- Known incomplete transaction-class validation.
- Backend payload service trust.
- Runtime equivalence.
- Proof-consumer rejection behavior.

No conditional claim is marked proved, approved, or production-ready.

## Known Counterexamples

The profile imports the disproof/counterexample report and separates confirmed counterexamples from missing-evidence vectors.

Known counterexamples include:

- Cleared native-vault assumptions without evidence.
- Signing path with removed authentication/vault precondition.
- Stale proof evidence accepted by a mutated consumer.
- Wrong-network signing after guard removal.
- Replay of a resolved payload after guard removal.
- Downgraded solver result accepted by a mutated consumer.
- Unsupported XRPL transaction semantics for TODO validation classes.

The backend double-use and runtime-equivalence disproof vectors remain blocked by missing evidence rather than being treated as proved safe.

## Unmodeled Components

The profile keeps unmodeled components separate from source-supported facts. Current blockers include native vault cryptography, biometric/passcode native security, third-party signing libraries, backend payload authorization and single-use behavior, native QR/deep-link intake integrity, XRPL consensus and node honesty, incomplete TrustSet/OfferCreate/SignerListSet validation, ledger service runtime trust, and deployed runtime equivalence.

Runtime gaps from `runtime-trace-report.json` are also included because source and e2e feature files are monitor specifications, not real-device execution evidence.

## External Assumptions

The profile preserves all blocking assumptions from `security-claims.json`:

- `xaman-assumption:native-vault-crypto-and-biometric-security`
- `xaman-assumption:backend-payload-api-auth-single-use-and-expiration`
- `xaman-assumption:xrpl-consensus-node-honesty-and-finality`
- `xaman-assumption:deployed-runtime-equivalence`
- `xaman-assumption:incomplete-transaction-class-validation`
- `xaman-assumption:proof-consumer-kernel-validation`

These assumptions are not cleared by public source review.

## Solver Coverage Gaps

Solver evidence remains fail-closed:

- Z3/CVC5 agreement currently shows all 10 claims blocked by unresolved assumptions; this is not a safety proof.
- Apalache is unavailable, so TLA invariants have not been model checked.
- Tamarin and ProVerif are unavailable, so protocol projections have not been proved.
- The Lean proof-consumer lane is checked, but Coq is unavailable and production integration remains unproved.

Missing or incomplete solver coverage cannot be used to accept a release.

## Vendor-Only Evidence

The JSON profile extracts vendor/operator-only evidence requirements from assumptions, missing-evidence vectors, and the assurance packet. Required evidence includes native vault or binary audit evidence, biometric/passcode threat-model evidence, backend source and traces, single-use and expiration tests, real-device runtime traces, build provenance, production environment profile, solver execution evidence, and production proof-consumer integration evidence.

Until that evidence exists and is reviewed, the public-source profile remains blocked.

## Regeneration

Regenerate the JSON profile with:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/build_xaman_public_source_assessment.py --out security_ir_artifacts/corpora/xaman-app/public-source-assessment.json
```

Validate with:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_public_source_assessment.py -q
```
