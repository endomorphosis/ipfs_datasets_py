# Shared wallet conformance fixtures

Chain-neutral offline vectors consumed by
`WalletProcessorConformance` / `FixtureTransport`.

Chain adapters **extend** these checks with native assertions; they must not
skip or weaken the shared suite listed in the parent `manifest.json`.

## Files

| File | Covers |
| --- | --- |
| `identity_vectors.json` | Address/network identity separation |
| `amount_vectors.json` | Exact base-unit amounts (no floats) |
| `deterministic_ids.json` | Canonical identity coordinates |
| `malformed_payloads.json` | Empty / malformed / partial provider data |
| `pagination_pages.json` | Cursor pagination and loops |
| `retry_and_cancel.json` | Retry classification and cancellation |
| `reorg_histories.json` | Shallow and deep reorg histories |
| `export_sample_records.json` | Export round-trip record shapes |
| `secret_redaction_cases.json` | Secret leak surface cases |
| `cas_checkpoint.json` | Checkpoint CAS conflict fixtures |
