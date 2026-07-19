# Xaman Self-Hosted Runtime Trace Contract

Task: `PORTAL-CXTP-158`

This contract prepares the evidence envelope for `PORTAL-CXTP-157`. It does
not record a wallet run, and it cannot make a security claim. Its purpose is
to prevent a later self-hosted run from silently omitting the paths that remain
blocked in the current public-source/Testnet assessment.

## Preconditions

- The endpoint-rebound candidate is the pinned public Xaman source commit
  `942f43876265a7af44f233288ad2b1d00841d5fa`.
- The isolated bridge report and daemon health report are present.
- An independent reviewer has passed and not expired the endpoint-rebind and
  bridge-isolation review.
- The run uses a fresh debug emulator on local XRPL network ID `777777`, with
  no observed external egress or vendor fallback.

## Required Categories

The reviewed categorical trace must record each category exactly once and in
this order:

1. onboarding
2. local network selection
3. review
4. signature decision
5. submit result
6. cancellation
7. expiry
8. replay, with a blocked duplicate-submit outcome
9. reconnect
10. network change, retaining the local network

Each event needs only a source digest, redaction digest, source kind, and
categorical outcome. It must retain no account identifiers, seeds, payloads,
transaction blobs, credentials, raw endpoints, or raw request/response bodies.

## Validation

Write the non-evidence template:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/validate_xaman_self_hosted_runtime_trace.py \
  --write-template
```

After an independently reviewed trace exists, validate it and generate the
redacted report:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/validate_xaman_self_hosted_runtime_trace.py \
  --trace security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/runtime-trace-review.json
```

Validation is fail-closed for a missing action, an invalid digest, an expired
or failed review gate, any raw sensitive value, external egress, vendor
fallback, a non-local network, vendor-release equivalence, or production
security result.

## Assurance Boundary

A successful report is only reviewed, self-hosted, public-source verifier
evidence. It does not establish that XRPL Labs released the tested build, that
vendor backend single-use/expiry behavior is secure, or that the production
wallet is secure. Those claims remain blocked pending vendor-authorized
evidence.
