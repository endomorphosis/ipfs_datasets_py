# Xaman To Production Blocker Bridge

Task: `PORTAL-CXTP-076`

This bridge connects the Xaman source-corpus assurance packet from
`PORTAL-CXTP-075` to the production blocker removal workflow. It records what
the reviewed Xaman artifacts can support, what they cannot support, and which
production evidence domains are still required before any blocker may be
removed.

Authoritative artifact:

`security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json`

## Identity

- Schema: `xaman-production-blocker-bridge/v1`
- Artifact CID: `bafkreia7mnvt6rqak2lxligdecw55xmm3fghgymrk33qbwbfm66kyag5km`
- Source assurance packet: `security_ir_artifacts/corpora/xaman-app/assurance-packet.json`
- Source assurance packet CID: `bafkreigzheeseiw36a5rqy3aggw4ia5gdkmzxlcmvmlnfluomr67ssjhzq`
- Model CID: `bafkreicugppxuacf5kxjsor7lqhwa3y44rrbsetiid2e65utlwgyablr5e`
- Corpus commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Decision carried forward: `blocked-production`

## Evidence Boundary

The bridge intentionally separates source-corpus evidence from deployed-app
evidence.

Source-corpus evidence is available and reviewed as context. It includes the
pinned source manifest, source coverage, security claims and assumptions,
security model IR, proof reports, disproof reports, source/e2e runtime monitor
facts, and the proof-consumer invariant fixture. This evidence is useful for
explaining blockers, but it is not accepted as deployed production evidence.

Deployed-app evidence is absent. The bridge records `accepted_evidence_count:
0`, `real_device_trace_count: 0`, and `production_release_ready: false` for
the deployed-app scope. Production blocker removal still needs evidence in all
five domains:

| Domain | Required evidence class |
| --- | --- |
| `production_source` | Reviewed production source, dependency, native module, backend, policy, or vendor evidence for the exact release boundary. |
| `production_build` | Reproducible-build, signed-binary, deployment digest, CI/CD attestation, or binary-to-source provenance. |
| `production_runtime` | Release-window runtime traces, real-device traces, integration tests, or backend/ledger execution traces bound to the deployed build. |
| `production_environment` | Production environment, custody, solver, node, platform, backend, or operational configuration evidence. |
| `human_review` | Named owner or security review accepting evidence scope, freshness, and residual risk. |

## Remaining Blockers

The source assurance packet contains 17 open blockers, and the bridge maps all
17 exactly once. All remain in `blocked_missing_production_evidence`.

| Source packet blocker | Required production evidence domains |
| --- | --- |
| `blocker:assumption:xaman-security-assumption-native-vault-cryptographic-confidentiality` | `production_source`, `production_build`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-passcode-kdf-and-secret-protection` | `production_source`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-biometric-native-binding` | `production_source`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-third-party-signing-correctness` | `production_source`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-backend-payload-api-single-use-and-authorization` | `production_source`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-intake-decoder-and-os-delivery-integrity` | `production_source`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-deployed-network-and-node-config-equivalence` | `production_build`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-trustset-and-signerlist-client-validation` | `production_source`, `production_runtime`, `human_review` |
| `blocker:assumption:xaman-security-assumption-xrpl-server-rule-enforcement-and-consensus` | `production_runtime`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-external-multisign-coordination` | `production_source`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-deployed-runtime-equivalence` | `production_source`, `production_build`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:assumption:xaman-security-assumption-proof-receipt-cid-or-signature-validation` | `production_source`, `production_build`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:proof:no-critical-claim-proved` | `production_source`, `production_build`, `production_runtime`, `production_environment`, `human_review` |
| `blocker:solver:apalache` | `production_environment`, `human_review` |
| `blocker:solver:proverif` | `production_environment`, `human_review` |
| `blocker:solver:tamarin-prover` | `production_environment`, `human_review` |
| `blocker:runtime:real-device-traces-absent` | `production_build`, `production_runtime`, `production_environment`, `human_review` |

Domain totals:

| Domain | Blocker count |
| --- | ---: |
| `production_source` | 11 |
| `production_build` | 6 |
| `production_runtime` | 13 |
| `production_environment` | 16 |
| `human_review` | 17 |

## Removal Policy

The bridge does not authorize blocker removal. It carries forward
`blocked-production` and sets `may_remove_any_blocker: false`.

A later production task may remove a mapped blocker only after:

- every listed production evidence domain for that blocker has current,
  reviewed evidence;
- deployed-app evidence is reviewed independently from source-corpus evidence;
- every affected blocking or high-risk claim has an accepted `PROVED` outcome
  bound to the release packet;
- a named human owner accepts the evidence scope, freshness, and residual risk.

The intake mechanism for future production evidence is documented in
`docs/security_verification/production_evidence_intake.md`; the current
environment scaffold is documented in
`docs/security_verification/production_environment_profile.md`.

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_production_blocker_bridge.py -q
```

The test regenerates `production-blocker-bridge.json` from the assurance
packet, verifies the artifact CID, checks the source-corpus/deployed-app
evidence boundary, maps every packet blocker exactly once, and confirms every
remaining blocker lists production source, build, runtime, environment, or
human review requirements.
