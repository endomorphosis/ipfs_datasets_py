# Xaman Testnet Transaction Lifecycle Trial

Task: `PORTAL-CXTP-130`

The transaction-lifecycle report is:

`security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-trial-report.json`

The redacted reviewed lifecycle evidence packet used to reproduce it is:

`security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-lifecycle-evidence.json`

It binds reviewed categorical lifecycle evidence to the pinned Xaman commit, verifier APK digest, isolated emulator profile, Testnet endpoint allow-list decision, and XRPL `server_info` response digest already captured by `PORTAL-CXTP-121`, `PORTAL-CXTP-125`, and `PORTAL-CXTP-126`.

## Result

The checked report status is `executed_with_coverage_gaps` with decision `TESTNET_TRANSACTION_LIFECYCLE_REVIEWED_WITH_COVERAGE_GAPS_NOT_PRODUCTION_EVIDENCE`.

Observed categorical actions:

- `payload_intake`
- `review`
- `auth_decision`
- `signing_decision`
- `submit_attempt`
- `submit_result`
- `reconnect`
- `network_switch`

Explicit coverage gaps:

- `decline`
- `cancel`
- `expiry`

The gaps are intentional evidence records, not silent omissions. They keep the trial usable for later model projection while preventing the report from implying that unexercised refusal, cancellation, or expiration paths were observed.

## Boundary

The report is public-Testnet only. It stores action names, event categories, categorical outcomes, source digests, redaction digests, coverage-gap reason codes, APK digest, endpoint key/digest, server-info digest, emulator-profile file digests, and local file `path_label` values only.

It rejects account addresses, X-addresses, seeds, credentials, bearer/JWT tokens, raw payload fields, transaction blobs, raw XRPL transaction JSON, signed transactions, raw `ws(s)://` or `http(s)://` endpoint URLs, raw request bodies, and raw response bodies before report emission. The redaction audit is applied to JSON values and object keys so sensitive material cannot be smuggled through field names. The checked report records `redaction_failure: false` and all raw-material flags as `false`.
Digest-suffixed fields are accepted only for reviewed evidence and dependency bindings; account-address, seed, payload, credential, signature, and transaction-blob digests remain outside the report boundary.

The inspected verifier APK must be present and digest-bound to the device and network-selection evidence. It remains classified as `firebase_js_stubbed_only`. Do not call the native-Firebase-packaged APK fully Firebase-disabled or production-equivalent. Production acceptance and runtime equivalence remain blocked.

The generator also fails closed when dependency provenance is inconsistent: the device trial, network-selection report, and native-Firebase boundary report must match the pinned commit and expected schema/task IDs; the verifier APK digest must match the device report and network build provenance; the Testnet endpoint key/digest and `server_info` request/response digests must be digest-only; both device and network reports must preserve a fresh Testnet account boundary; and an APK with native Firebase packaging cannot be labeled fully Firebase-disabled. Absolute local paths from the dependency reports are reduced to filename/profile labels before the transaction-trial report is emitted.
The network-selection dependency must also retain the reviewed Testnet event categories for fresh emulator profile, fresh Testnet account boundary, fresh Testnet account creation, Xaman network selection, and XRPL `server_info` observation, and its endpoint allow-list metadata must include a normalized endpoint key, normalized allow-list version, and positive allowed-endpoint count.

## Evidence Input

The script consumes a reviewed evidence packet with schema:

`xaman-testnet-transaction-lifecycle-evidence/v1`

Each observed lifecycle event must include:

- `ordinal`
- `action`
- `category`
- `outcome`
- `source_kind`
- `source_sha256`
- `redaction_sha256`
- `raw_material_recorded: false`

The evidence packet must use the exact schema version above and include
`reviewed_at_utc` at UTC second precision.
Observed event ordinals must be contiguous from `1` after sorting so the
reviewed lifecycle order cannot silently skip an event.

Every required action must have either one observed event or one coverage gap. The required actions are:

`payload_intake`, `review`, `auth_decision`, `signing_decision`, `submit_attempt`, `submit_result`, `decline`, `cancel`, `expiry`, `reconnect`, and `network_switch`.

Observed events must carry a reviewed source digest and a redaction digest, and
their outcome must match the action category: for example, `payload_intake`
may be `accepted` or `blocked`, `submit_result` may be `succeeded` or
`failed`, and `network_switch` must be `switched_to_testnet`. Coverage gaps
must include a reviewed note digest. Missing digests, placeholder digests such
as a single repeated hex character, action/outcome mismatches, duplicate
actions, overlap between an observed action and a gap, or an unaccounted action
block the report.
The lifecycle evidence schema is closed: unknown top-level evidence fields,
event fields, or coverage-gap fields block the report instead of being copied
forward.

Dependency reports are also fail-closed. Their schema, task ID, artifact CID,
pinned commit, APK digest, fresh-account boundary, emulator profile file
digests, Testnet endpoint digest, and `server_info` digest must validate and
must not use placeholder repeated-character SHA-256 values. The device-trial
and network-selection reports must also carry the accepted Testnet-only
security decisions from their source tasks. The native-Firebase boundary must
have a recognized audit status and state both native-packaging presence and
fully-disabled status; unknown status, a fully-disabled claim without a passing
native audit, packaged native Firebase labeled fully disabled, a packaged APK
without the packaged-native-Firebase blocker decision, or a non-`firebase_js_stubbed_only`
device-trial label blocks the transaction-lifecycle report.

## Regeneration

Run the generator with the checked-in redacted lifecycle evidence:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/capture_xaman_testnet_transaction_trial.py \
  --device-report security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json \
  --network-report security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json \
  --native-firebase-report security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json \
  --generated-at-utc 2026-07-10T23:30:00Z \
  --out security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-trial-report.json
```

Use `--lifecycle-evidence /path/to/reviewed-redacted-evidence.json` only when replacing the reviewed evidence packet for a new trial. The replacement must use the same schema and redaction boundary.

The verifier returns exit code `0` only for `executed_complete` or `executed_with_coverage_gaps`. Evidence failures produce a blocked report and exit code `2`; redaction violations fail before writing a report.

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_xaman_testnet_transaction_trial.py -q

PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/capture_xaman_testnet_transaction_trial.py --help
```
