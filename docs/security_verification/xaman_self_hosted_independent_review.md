# Xaman Self-Hosted Independent Review

Tasks: `PORTAL-CXTP-160`, `PORTAL-CXTP-161`

The automated packet binds the endpoint-rebound candidate, standalone daemon
health, and bridge-isolation reports by content ID. It is explicitly
`PENDING_INDEPENDENT_REVIEW`; it is not a review and does not authorize a
runtime capture.

Generate the packet and non-evidence template:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/build_xaman_self_hosted_review_packet.py \
  --write-template
```

An independent reviewer must use the template to create
`endpoint-rebind-review.json`. The decision must contain digest-only reviewer
identity, a conflict-of-interest attestation, an expiry, a pass/fail result,
and a pass/fail result for every required check. It must bind the packet CID
and remain scoped to the verifier-only public-source candidate.

Validate a completed decision:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/build_xaman_self_hosted_review_packet.py \
  --review security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/endpoint-rebind-review.json
```

A valid, unexpired pass permits only the redacted verifier-runtime capture in
`PORTAL-CXTP-157`. It cannot establish vendor-release equivalence, clear
vendor backend assumptions, or establish production wallet security.
