# Xaman Self-Hosted Resolution Protocol Model

Task: `PORTAL-CXTP-159`

This is a conditional theorem-prover lane for the self-hosted bridge, not a
model of the XRPL Labs backend or production wallet. It requires the bridge
review to establish the key local assumption: a payload has one linear `Open`
state which is consumed by submit, cancellation, or expiry.

The Tamarin model proves that a local payload has at most one accepted submit,
that cancellation and expiry block a later submit, and that replay blocking
follows an accepted submit. The ProVerif projection independently checks the
causal ordering of issued, submitted, cancelled, expired, and replay-blocked
events.

Run both solver checks:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/generate_xaman_self_hosted_resolution_protocol.py \
  --run-solver
```

The resulting report remains production-blocked. It cannot prove vendor
backend payload single-use or expiry semantics, native vault security, XRPL
broadcast finality, release equivalence, or wallet security. Those require
separate runtime and vendor-authorized evidence.
