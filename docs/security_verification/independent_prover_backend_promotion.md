# Independent Prover Backend Promotion

Date: 2026-07-07

Scope: promotion criteria for CVC5, TLA/Apalache, Tamarin/ProVerif, Lean/Coq, HyperLTL, and any future prover backend that may contribute to crypto-exchange release decisions.

The current release-authoritative backend is Z3 over the bounded `SecurityModelIR`. Other prover families are planning targets until they execute end to end, emit proof reports or linked artifacts, and fail closed through the same release-gate workflow.

## Promotion Rule

A prover backend may support production release claims only after all of these are true:

- It has an executable runner or explicit adapter in the repository.
- It has deterministic tests that run in CI.
- It can consume either `SecurityModelIR` or a reviewed projection from it.
- It emits machine-readable results linked to model CID, claim ID, prover name, prover version, and environment profile.
- It maps unsupported claims, missing executables, timeouts, parser errors, solver errors, and unsupported theories to fail-closed outcomes.
- It has at least one positive fixture and one counterexample fixture.
- It is included in release documentation with a clear soundness boundary.
- It is not used to broaden production claims beyond what the encoded model actually covers.

## Backend Order

### 1. CVC5

Purpose: independent SMT cross-checking for the current Z3-bounded claims.

Required work:

- Add `runners/cvc5_runner.py` or equivalent.
- Reuse SMT-LIB2 serialization where practical.
- Compare Z3 and CVC5 results for current claims.
- Record CVC5 version, timeout, and unsupported-theory results.
- Fail closed on disagreement for blocking and high-risk claims.

Promotion tests:

- Example model proves the same blocking/high claims as Z3.
- Known-bad disproof vectors are rejected.
- Missing CVC5 binary returns `UNKNOWN` or a configured unavailable state, not success.
- Timeout on a critical claim blocks release.

### 2. TLA/Apalache

Purpose: workflow and concurrency checking outside the finite snapshot encoded for SMT.

Required work:

- Encode withdrawal lifecycle transitions.
- Encode ledger reservation and commit interleavings.
- Encode freeze/signing race conditions.
- Encode deposit finality and reorg handling.
- Link generated counterexamples to proof reports or release artifacts.

Promotion tests:

- Safe workflow model passes.
- Double reservation interleaving fails.
- Signing after freeze interleaving fails.
- Deposit rollback or reorg trace fails.
- Missing Apalache/TLA executable blocks release if the backend is configured as required.

### 3. Tamarin or ProVerif

Purpose: protocol reasoning for key custody, signing authority, replay, delegation, and revocation propagation.

Required work:

- Model HSM/key-manager request and response protocol.
- Model authentication and replay resistance.
- Model capability token delegation.
- Model revocation propagation and reinstatement.
- Model secrecy properties for key material and signing authorization.

Promotion tests:

- Safe custody protocol verifies.
- Replay attack is rejected.
- Revoked capability cannot authorize a later privileged action.
- Protocol proof artifacts include model version and threat assumptions.

### 4. Lean or Coq

Purpose: proof-consumer and artifact invariants, not operational exchange behavior.

Required work:

- Formalize proof report schema invariants.
- Formalize proof receipt acceptance invariants.
- Formalize canonical payload construction or CID binding assumptions.
- Check that consumer acceptance cannot succeed on `DISPROVED`, `UNKNOWN`, or `NOT_MODELED` reports.

Promotion tests:

- Proof receipt validity implies matching claim ID and model CID.
- Accepted assumptions cover report assumptions.
- Unsupported report statuses cannot pass.
- Canonicalization assumptions are explicit and versioned.

### 5. HyperLTL Or Equivalent

Purpose: hyperproperty and noninterference claims that cannot be expressed as ordinary single-trace safety checks.

Required work:

- Identify concrete leakage or noninterference properties.
- Define minimal trace-pair models.
- Define which runtime traces supply evidence.
- Keep unchecked hyperproperties out of production release gates.

Promotion tests:

- Safe trace-pair fixture passes.
- Deliberate leakage fixture fails.
- Unsupported trace relation produces fail-closed output.

## Report Integration

Every promoted backend must produce or reference a report with:

- `claim_id`
- `model_cid`
- `status`
- `prover`
- `solver_name` or tool name
- `solver_version` or tool version
- `proof_or_trace_cid`
- `assumptions`
- `risk`
- `evidence_refs`
- `soundness_notes`
- counterexample details when disapproved

If a backend cannot emit the existing proof report schema directly, it must emit an adapter artifact and a reviewed mapping into the release-gate packet.

## Fail-Closed Mapping

| Backend Result | Release Mapping |
| --- | --- |
| proved supported claim | `PROVED`, subject to evidence and assumption policy |
| counterexample found | `DISPROVED` |
| timeout | `UNKNOWN` |
| unsupported theory or feature | `UNKNOWN` or `NOT_MODELED` |
| parser/type error | `UNKNOWN` |
| missing executable | `UNKNOWN` |
| backend disagreement | release failure for blocking/high claims |
| stale backend version | release failure until reviewed |

## Production Authority

A backend is production-authoritative only after it is listed in the release runbook and CI gate. Until then, it may provide advisory evidence but cannot turn a rejected or inconclusive release into an accepted one.
