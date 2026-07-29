# Xaman Release Decision

Task: `PORTAL-CXTP-075`

Decision: reject release.

The current Xaman assurance packet cannot support a claim that the wallet/signing flow is secure for production. The decision is based on the packet at `security_ir_artifacts/corpora/xaman-app/assurance-packet.json`.

## Basis

The release is blocked because:

- Blocking/high claims still depend on unresolved assumptions.
- Z3/CVC5 agree on the assumption-blocking encoding, but no claim is cleared for release.
- The disproof suite found counterexamples and missing evidence gaps.
- Real-device runtime equivalence traces are missing.
- TLA/Apalache, Tamarin/ProVerif, and Coq coverage is unavailable or incomplete.
- The Lean proof-consumer kernel compiles, but it is not wired into production proof consumption.

## What This Means

This is a useful negative result. The current evidence disproves the stronger statement that the system is already proved secure under production assumptions. It does not prove that Xaman is insecure in every possible deployment; it means the current code-and-environment evidence is insufficient and contains concrete blockers.

## Conditions To Reconsider

Reconsider the release decision only after:

- Production environment and source inventory evidence is supplied and reviewed.
- A production `SecurityModelIR` candidate is generated from that evidence.
- Required production domains and claim minimums pass.
- Runtime traces from real devices cover the required signing workflow categories.
- Solver lanes are installed, run, or explicitly scoped out with reviewed rationale.
- All blocking/high proof reports are `PROVED`, assumption-cleared, evidence-reviewed, and accepted by the production proof consumer.
