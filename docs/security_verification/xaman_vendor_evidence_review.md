# Xaman Vendor Evidence Review Packet (PORTAL-CXTP-153)
Task: `PORTAL-CXTP-153`

This packet defines how authorized vendor evidence is collected and reviewed for
native, backend, and XRPL/RPC trust assumptions that cannot be resolved from
public source or testnet-only artifacts alone.

Generate a placeholder manifest and optional review template:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/build_xaman_vendor_evidence_packet.py \
  --write-review-template
```

The command writes:

- `security_ir_artifacts/corpora/xaman-app/vendor-evidence-manifest.json`
- `security_ir_artifacts/corpora/xaman-app/vendor-evidence-review-template.json` (optional)

When a vendor review is prepared, validate it against the manifest:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/build_xaman_vendor_evidence_packet.py \
  --review security_ir_artifacts/corpora/xaman-app/vendor-evidence-review.json
```

Expected validation output is a `review_verification` artifact at:

- `security_ir_artifacts/corpora/xaman-app/vendor-evidence-review-verification.json`

The gap-remediation workflow (`PORTAL-CXTP-172`) treats `EXTERNAL_EVIDENCE_REQUIRED`
entries as blocked until this review validates as accepted for the entry’s claim.
`review_accepted_for_gap_clearance` must be `true`, and all required claim
category evidence bindings must be evidence-received and redaction-reviewed.
