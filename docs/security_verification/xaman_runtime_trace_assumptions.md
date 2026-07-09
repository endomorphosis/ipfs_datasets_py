# Xaman Runtime Trace Assumptions

Task: `PORTAL-CXTP-074`

The machine-readable runtime trace report is `security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json`.

## Source Boundary

- Corpus: `xaman-app`
- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Manifest aggregate SHA-256: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`
- Coverage artifact: `security_ir_artifacts/corpora/xaman-app/source-coverage.json`

The report ingests the manifest-pinned e2e feature declarations and projects reviewed source facts from `PORTAL-CXTP-061`, `PORTAL-CXTP-065`, and `PORTAL-CXTP-066` into monitor facts. It also accepts optional JSON or NDJSON runtime traces through `XamanRuntimeTraceIngestor` and normalizes them to the same monitor vocabulary.

## Monitor Vocabulary

The runtime monitor facts cover these categories:

- `payload_intake`: QR, deep-link, push, and event-list payload reference intake.
- `review`: review preflight and user-visible transaction review.
- `auth`: passcode or biometric authentication before vault-backed signing.
- `signing`: approved transaction signing and signed payload patching.
- `rejection`: user or app rejection before signing.
- `expiration`: expired or already-resolved payload blocking.
- `network_binding`: forced network, node, and NetworkID binding.
- `broadcast`: optional XRPL submit after signed payload patch and submit guards.

The checked-in report contains monitor facts for all eight categories. E2e feature declarations are marked `source_declared_not_runtime_equivalent`; reviewed source facts are marked as monitor facts but carry `real_device_required_for_runtime_equivalence: true`.

## Blocking Runtime Equivalence

The checked-in Xaman corpus does not include real-device runtime traces. Because of that, the report sets:

`blocking_runtime_equivalence.status = BLOCKING`

and records the gap:

`xaman-runtime-trace:gap:real-device-runtime-traces-absent`

This blocks acceptance of `xaman-security:claim:reviewed-source-is-equivalent-to-deployed-runtime`. E2e feature declarations and source review can define the expected monitor facts, but they do not prove app-store binary behavior, native module behavior, mobile OS delivery, backend deployment, node endpoint configuration, or release-window device behavior.

To discharge the gap, the release packet needs iOS and Android real-device traces that cover payload intake, review, auth, signing, rejection, expiration, network binding, and broadcast. Each trace must bind app build identifier, source commit, backend environment, node URI, device OS, capture time, and binary provenance or reproducible-build evidence.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py -q
```

The tests validate report regeneration, source and manifest binding, e2e feature ingestion, runtime event normalization, monitor coverage, explicit `BLOCKING` runtime-equivalence status, and documentation coverage.
