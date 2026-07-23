# Xaman Testnet Network Selection

Task: `PORTAL-CXTP-125`

## Result

`security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json` records a verifier-only proof that the fresh Xaman Testnet profile selected `TESTNET`, matched one public XRPL Testnet endpoint from the reviewed allow-list, and received an XRPL `server_info` response with `network_id: 1`.

The report status is `verified` with decision `TESTNET_NETWORK_SELECTION_VERIFIED_NOT_PRODUCTION_EVIDENCE`. Production release and runtime-equivalence conclusions remain blocked.
Evidence failures appear in `blocking_gaps`; the checked report has none. The
standing production/runtime-equivalence limitation is retained separately in
`residual_boundaries`.

## Boundary

The report stores only:

- event categories,
- the selected network key,
- the endpoint allow-list decision, endpoint key, and endpoint/source-node digests,
- SHA-256 digests for the selected endpoint, canonical `server_info` request,
  and `server_info` response,
- redacted dependency metadata and digests for the Firebase-disabled build kit,
  the Testnet telemetry report, and the React Native Navigation compatibility
  overlay when those inputs are supplied.

It does not store classic account addresses, X-addresses, seeds, credentials, API keys, bearer/JWT tokens, payloads, transaction blobs, raw WebSocket request bodies, raw response bodies, or the raw endpoint URL. Inputs that include those fields, including bearer credentials or stringified raw `server_info` request bodies pasted into free-text notes, fail before report emission.

## Evidence

The source review binds Xaman's in-app `TESTNET` network definition at commit `942f43876265a7af44f233288ad2b1d00841d5fa` to:

- network key: `TESTNET`
- network id: `1`
- allowed endpoints: `wss://testnet.xrpl-labs.com` and `wss://s.altnet.rippletest.net:51233`

The checked report also binds the runtime dependency lane to:

- `PORTAL-CXTP-119` Firebase-disabled Testnet build manifest CID `sha256:b036f7221ee476c16a1b817cb1bb26c5c6de71d1ea4e040f875a9b9889422544`
- `PORTAL-CXTP-120` Testnet telemetry report CID `sha256:ee11d41c8f6c2d6ca2de0d623ece01d08fcb58fda09d051182c4403908238f1d`
- `PORTAL-CXTP-123` React Native Navigation overlay digest `c7ea6acd4300e8645644facc9f5c31dd8e601d29b890d6b7c0e55fffcd318f99`

The deterministic fresh-profile setup records that the selected profile was fresh, the active network key was `TESTNET`, and any account boundary was Testnet-only with no imported or production account material. The selected endpoint is bound back to Xaman's reviewed `TESTNET` node list by endpoint key and SHA-256 digest only. A live WebSocket `server_info` request was then sent to the selected allow-listed endpoint. The raw request body and raw response were not written to the artifact; only the canonical request digest `6a1a5cf3644551cf735838bfa1ada32fe420c979bac41dd497fbc13f229070c3`, response digest, and extracted `network_id: 1` were retained.

The required categorical events are `fresh_emulator_profile`,
`xaman_network_selected`, `fresh_testnet_account_boundary`, and
`xrpl_server_info_observed`. Deterministic setup evidence must also include
`deterministic_testnet_local_state`; reviewed UI evidence must include
`reviewed_ui_testnet_selection`. `fresh_testnet_account_created` is permitted
only when the fresh Testnet profile actually needed a new Testnet account, and
the fresh-account `created` flag must agree with that event category.

## Reproduction

Create reviewed selection evidence outside the repository, then run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/capture_xaman_testnet_network_selection.py capture \
  --selection-evidence /path/to/selection-evidence.json \
  --endpoint wss://s.altnet.rippletest.net:51233 \
  --network-constants /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app/src/common/constants/network.ts \
  --build-kit-manifest /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit/testnet-build-manifest.json \
  --telemetry-report security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json \
  --rnn-compat-overlay /home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit/react-native-navigation-compat/ReactTypefaceUtils.java \
  --run-id xaman-testnet-network-selection-20260710 \
  --build-provenance-sha256 c22cd33b580dd0ecd8b8c5529b42169dccb79676ac396cda8af448d31810a41d \
  --out security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json
```

For offline CI, use `report` with a reviewed `server_info` response fixture. The same validator still requires `TESTNET`, an allow-listed endpoint, Xaman source constants that match the allow-list, and `network_id: 1`.
The supplied or live response must also be a successful XRPL-style
`server_info` response with a `result.info` object. If the response includes
an XRPL `type` field, it must be `response`; if it includes an echoed request
`id`, it must be bound to the verifier's `server_info` request. A generic JSON
object that only contains `network_id: 1` is blocked.

## Fail-Closed Cases

The capture blocks when:

- the selected network key is not `TESTNET`,
- the endpoint is not exactly one of the two public XRPL Testnet endpoints,
- the Xaman source network definition no longer has network id `1` and exactly those two nodes,
- supplied dependency evidence contradicts the pinned Firebase-disabled build,
  telemetry, or React Native Navigation overlay lanes, including malformed
  dependency artifact CIDs,
- the `server_info` response does not show `network_id: 1`,
- the response type or echoed request id contradicts the verifier's
  `server_info` request,
- fresh-profile, network-selection, server-info, or fresh-account boundary
  event categories are missing,
- deterministic local-state or reviewed UI evidence is missing its matching
  proof category,
- the fresh Testnet account-created event and the fresh-account `created` flag
  disagree,
- fresh-profile or fresh-account boundary fields are missing,
- any input includes account material, seeds, credentials, API keys, bearer/JWT
  tokens, payloads, transaction blobs, raw request-body keys, or a raw
  `server_info` request body identified by its `command`, including a
  stringified request pasted into free text,
- the emitted report would include a raw WebSocket endpoint, account address,
  seed, or transaction-sized hex blob.

This evidence clears the Testnet network-selection gap for the verifier lane only. It does not clear the native Firebase boundary, production release, or deployed-runtime equivalence blockers.
