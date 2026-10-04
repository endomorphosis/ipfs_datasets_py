# Proof Receipt Consumer Policy

Date: 2026-07-07

Scope: TypeScript, WASM, MCP, SwissKnife, browser, runtime, and deployment consumers that evaluate crypto-exchange proof reports and proof receipts.

This policy defines how consumers may use proof artifacts. It does not make raw proof JSON authoritative. A consumer must validate the receipt, report, model binding, assumption set, evidence status, and deployment context before using a theorem-prover result to allow an exchange release or runtime action.

## Consumer Modes

### Schema-Only Mode

Schema-only mode is allowed for dashboards, development views, artifact browsing, and non-production observability.

Schema-only mode may:

- Validate proof report and proof receipt shapes.
- Check `PROVED`, `DISPROVED`, `UNKNOWN`, and `NOT_MODELED` status fields.
- Check that receipt `claim_id` and `model_cid` match the proof report.
- Check accepted assumptions listed in the receipt.
- Display proof and disproof summaries.

Schema-only mode must not:

- Authorize a production release.
- Authorize a withdrawal, signing request, wallet unfreeze, or privileged action.
- Treat report CIDs as cryptographic proof unless the runtime recomputes canonical CIDs byte-for-byte or verifies a trusted signature.

### Proof-Critical Mode

Proof-critical mode is required for production deployment gates and runtime enforcement.

Proof-critical mode must fail closed unless all of these are true:

- The proof receipt and proof report pass strict schema validation.
- The proof report status is `PROVED`.
- The proof report claim is expected for the release gate.
- The proof report model CID matches the exact production `SecurityModelIR`.
- The receipt model CID matches the report model CID.
- The receipt claim ID matches the report claim ID.
- The receipt report schema version matches the report schema version.
- The receipt proof report CID matches the selected deterministic or nondeterministic report CID policy.
- Every report assumption is explicitly listed in the receipt `accepted_assumptions`.
- Every consumed assumption is current, owned, evidenced, and accepted in the production assumption registry.
- Blocking and high-risk claims have `human_reviewed` or equivalent trusted evidence.
- The report prover is supported for this consumer and release policy.
- The report does not depend on simulated F-logic, simulated ZKP, or unavailable prover components.
- The report or receipt carries a trusted signature, or the consumer can recompute the canonical report CID byte-for-byte.
- The model CID and environment profile have not expired or drifted since the release baseline.

The generated TypeScript schema currently makes `verifyProofReceiptProofCritical()` fail closed until canonical CID recomputation or trusted signature verification is available in that runtime. That is intentional.

## Required Artifacts

Production proof consumers require:

- Production `SecurityModelIR` CID.
- Proof report JSON for each blocking and high-risk claim.
- Proof receipt JSON for each accepted claim.
- Accepted assumptions file.
- Assumption registry summary.
- Release-gate summary.
- Evidence review summary.
- Prover/version allowlist.
- Environment profile and freshness metadata.
- Trusted signing policy or canonical CID recomputation implementation.

## Accepted Status Policy

Consumers must use this status policy by default:

| Status | Production Consumer Result |
| --- | --- |
| `PROVED` | Accept only when all receipt, assumption, evidence, model, and signature checks pass. |
| `DISPROVED` | Reject. Treat attached counterexample as release-blocking evidence. |
| `UNKNOWN` | Reject for blocking and high-risk claims. |
| `NOT_MODELED` | Reject for blocking and high-risk claims. |

No consumer may accept a blocking or high-risk proof report because it is missing from the packet, because the claim is not modeled, or because the prover returned unknown.

## CID Policy

Consumers must choose one proof report CID policy and use it consistently:

- `deterministic`: compare the receipt to `deterministic_payload_cid`.
- `nondeterministic`: compare the receipt to `nondeterministic_report_cid`.

Production consumers should prefer deterministic CID verification once the TypeScript/WASM runtime can reproduce Python canonicalization byte-for-byte. Until then, production consumers must require a trusted signature over the proof report or receipt bundle.

## Assumption Policy

Consumers must reject receipts when:

- `accepted_assumptions` is empty.
- A report assumption is missing from `accepted_assumptions`.
- An accepted assumption is not part of the report.
- An assumption is stale, expired, ownerless, or unevidenced in the production registry.
- An assumption was accepted only by copying report assumptions through an unsafe test-only mode.

The test-only `--unsafe-accept-report-assumptions` path may be used for fixtures, not production.

## Evidence Policy

For blocking and high-risk claims:

- `human_reviewed` or equivalent trusted evidence is required.
- `heuristic` and `machine_extracted` evidence are discovery inputs, not production proof authority.
- Source evidence should include path, line span, digest, and review status.
- Policy, API, log, HSM, RPC, and audit evidence should include owner, review timestamp, expiry timestamp, and source reference.

## Runtime Consumer Policy

Runtime consumers must not use proof receipts as a substitute for live enforcement. They may use receipts to configure or attest expected invariants, but must still:

- Enforce wallet freeze checks before signing.
- Enforce withdrawal request, approval, nonce reservation, and balance reservation checks.
- Enforce deposit finality and reorg handling.
- Enforce capability revocation before privileged actions.
- Emit audit events for critical transitions.
- Treat runtime monitor violations as counterexample evidence.

## Generated Schema Artifact

The current generated schema artifact is:

- `security_ir_artifacts/assurance-run/security-ir-schema.ts`

Regenerate it from `external/ipfs_datasets` with:

```bash
PYTHONPATH=. python scripts/ops/security_verification/emit_security_typescript_schema.py \
  --example \
  --out security_ir_artifacts/assurance-run/security-ir-schema.ts
```

## Production Acceptance

A consumer implementation is production-ready only after tests prove that it rejects:

- Invalid proof report schema.
- Invalid proof receipt schema.
- `DISPROVED`, `UNKNOWN`, and `NOT_MODELED` reports.
- Mismatched claim ID.
- Mismatched model CID.
- Mismatched report CID.
- Missing accepted assumptions.
- Stale or ownerless assumptions.
- Unsupported prover names.
- Simulated proof dependencies.
- Unreviewed blocking or high-risk evidence.
- Missing or invalid trusted signature when canonical CID recomputation is unavailable.
