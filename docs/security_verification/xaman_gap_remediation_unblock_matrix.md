# Xaman Gap Remediation Unblock Matrix

This matrix links unresolved gap entries to the explicit unblock tracks after the latest remediation pass.

## Runtime / Backend Semantic Gaps (manual capture tasks)

| Gap ID | Claim | Blocking Class | Next Actions | Runtime Unblock Task Path |
|---|---|---|---|---|
| `attack-cancel-after-submit-race` | xaman-testnet-claim:cancellation-path-is-not-modeled | UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS | Collect redacted runtime categories and backend contracts for the target claim.; Feed observed evidence back into claim-to-source mappings before any claim promotion. | `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` |
| `attack-cancel-gap-promoted` | xaman-testnet-claim:cancellation-path-is-not-modeled | UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS | Collect redacted runtime categories and backend contracts for the target claim.; Feed observed evidence back into claim-to-source mappings before any claim promotion. | `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` |
| `attack-decline-gap-promoted` | xaman-testnet-claim:refusal-path-is-not-modeled | UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS | Collect redacted runtime categories and backend contracts for the target claim.; Feed observed evidence back into claim-to-source mappings before any claim promotion. | `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` |
| `attack-expiry-after-auth-race` | xaman-testnet-claim:expiry-path-is-not-modeled | UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS | Collect redacted runtime categories and backend contracts for the target claim.; Feed observed evidence back into claim-to-source mappings before any claim promotion. | `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` |
| `attack-expiry-gap-promoted` | xaman-testnet-claim:expiry-path-is-not-modeled | UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS | Collect redacted runtime categories and backend contracts for the target claim.; Feed observed evidence back into claim-to-source mappings before any claim promotion. | `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` |
| `attack-reconnect-before-submit-result-race` | xaman-testnet-claim:submission-ui-attempt-and-result-are-observed | UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS | Collect redacted runtime categories and backend contracts for the target claim.; Feed observed evidence back into claim-to-source mappings before any claim promotion. | `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` |
| `attack-replay-duplicate-resolution` | xaman-testnet-claim:replay-controls-are-not-modeled | UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS | Collect redacted runtime categories and backend contracts for the target claim.; Feed observed evidence back into claim-to-source mappings before any claim promotion. | `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` |
| `attack-replay-duplicate-submit-result` | xaman-testnet-claim:replay-controls-are-not-modeled | UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS | Collect redacted runtime categories and backend contracts for the target claim.; Feed observed evidence back into claim-to-source mappings before any claim promotion. | `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` |
| `attack-submit-result-removed` | xaman-testnet-claim:submission-ui-attempt-and-result-are-observed | UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS | Collect redacted runtime categories and backend contracts for the target claim.; Feed observed evidence back into claim-to-source mappings before any claim promotion. | `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` |

## External Evidence Gaps

| Gap ID | Claim | Blocking Class | External Unblock Task Path |
|---|---|---|---|
| `xaman-disproof:backend-double-use` | xaman-claim:backend-payload-service-is-trusted-not-proved | EXTERNAL_EVIDENCE_REQUIRED | `PORTAL-CXTP-152` -> `PORTAL-CXTP-153` |
| `xaman-disproof:runtime-equivalence-missing` | xaman-claim:runtime-equivalence-is-blocked-without-device-traces | EXTERNAL_EVIDENCE_REQUIRED | `PORTAL-CXTP-152` -> `PORTAL-CXTP-153` |

## Dependency notes
- `PORTAL-CXTP-157` / `PORTAL-CXTP-163` / `PORTAL-CXTP-168` evidence paths are now represented in runtime-conformance and runtime preflight artifacts, and `UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS` gaps are therefore no longer hard-blocked by these task IDs.
- `PORTAL-CXTP-153` remains the blocker for vendor-sourced trust/evidence gaps.
