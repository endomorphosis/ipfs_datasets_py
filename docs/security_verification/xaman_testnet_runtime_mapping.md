# Xaman Testnet Runtime Monitor Mapping

Task: `PORTAL-CXTP-122`

The machine-readable mapping is:

`security_ir_artifacts/corpora/xaman-app/runtime/testnet-monitor-mapping.json`

## Result

The mapping status is `mapped_with_gaps_not_production_evidence`.

Only approved redacted public-Testnet events are admitted. The mapping binds
those events to the monitor categories from `PORTAL-CXTP-074` and keeps absent
or unexplained categories as explicit gaps. It does not promote any Testnet
event to a production-security, native-runtime-equivalence, or production
runtime-equivalence conclusion.

## Accepted Evidence

The mapping consumes reviewed categorical evidence from:

| Artifact | Use |
| --- | --- |
| `runtime-trace-report.json` | Baseline runtime monitor fact IDs and categories. |
| `runtime/testnet-telemetry-report.json` | Four redacted Firebase JavaScript stub events. |
| `runtime/testnet-device-trial-report.json` | Public-Testnet debug verifier, fresh profile, APK, and redaction boundaries. |
| `runtime/testnet-network-selection-report.json` | `TESTNET` selection, endpoint allow-list digest, and `server_info` digest with `network_id: 1`. |
| `runtime/testnet-transaction-trial-report.json` | Reviewed categorical lifecycle events and coverage gaps. |

The admitted values are categories, action names, categorical outcomes, event
ordinals, digests, aggregate counts, network key, endpoint key, and file/APK
hashes. Raw endpoints, account identifiers, seeds, credentials, payloads,
transaction blobs, signed transactions, raw request bodies, raw response bodies,
and Firebase attributes are outside the mapping boundary.

## Monitor Mapping

| Runtime monitor category | Testnet mapping | Residual gap |
| --- | --- | --- |
| `payload_intake` | `payload_intake` was observed as accepted in reviewed UI evidence. | Raw payload JSON, payload semantic validation, and digest-to-payload binding are absent. |
| `review` | `payload_review` was observed as reviewed. | Displayed raw payload fields are not present. |
| `auth` | `auth_decision` was observed as authorized, with fresh Testnet account boundary evidence. | No passcode, biometric, secure-enclave, vault-key, or native auth transcript was recorded. |
| `signing` | `signing_decision` was observed as signed. | No signature bytes, signed transaction blob, native vault cryptographic output, or digest-to-signed-byte proof was recorded. |
| `rejection` | No accepted event maps to the rejection monitor. | `decline` was not exercised; backend refusal propagation is absent. |
| `expiration` | No accepted event maps to the expiration monitor. | `expiry`, replay, duplicate submit handling, and backend atomic single-use behavior are absent. |
| `network_binding` | `xaman_network_selected`, `xrpl_server_info_observed`, and `network_switch` map to a Testnet-only network-binding observation. | Wrong-network refusal, unsupported-type rejection, production endpoint binding, and endpoint authenticity beyond the public Testnet allow-list are not proved. |
| `broadcast` | `submit_attempt`, `submit_result`, and `reconnect` map to a categorical Testnet submit flow. | Raw XRPL submit material, transaction hash, mempool/queue state, validated-ledger inclusion, and finality are absent. |
| `runtime_equivalence` | No event maps to a proof of runtime equivalence. | Debug verifier and emulator evidence remain non-production; native Firebase packaging remains present. |

Firebase stub events are recorded only as a supplemental `firebase_boundary`
record. They show that JavaScript Firebase calls were stubbed into redacted
local telemetry. They do not map to wallet, account, payload, signing, XRPL
network, broadcast, or ledger-finality monitor facts.

## Preserved Gaps

- `cancel` was not exercised.
- `decline` was not exercised.
- `expiry` was not exercised.
- Replay, duplicate resolution, and backend atomic single-use behavior were not traced.
- Raw payload material, signatures, signed transaction blobs, and native vault cryptographic correctness were not traced.
- XRPL broadcast request material and validated-ledger finality were not traced.
- Production runtime equivalence and native-runtime equivalence are not proved.
- Full Firebase-disabled labeling is blocked because native Firebase packaging remains present in the inspected APK.

## Prohibited Conclusions

This mapping must not be used to conclude that public-Testnet telemetry proves
production Xaman security. It must not be used to conclude that the debug
verifier APK or emulator trace is equivalent to a production runtime. It must
not be used to infer wallet, account, payload, signing, transaction, XRPL
broadcast, or ledger-finality facts from Firebase stub telemetry.

The only accepted use is Testnet-scoped monitor projection with the gaps above
preserved for later evidence collection.

## Validation

```bash
test -f security_ir_artifacts/corpora/xaman-app/runtime/testnet-monitor-mapping.json
test -f docs/security_verification/xaman_testnet_runtime_mapping.md
```
