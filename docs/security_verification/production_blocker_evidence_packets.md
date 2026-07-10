# Production Blocker Evidence Packets

Task: `PORTAL-CXTP-094`

This task generates one evidence packet for each remaining production blocker. The packets are scaffolds for production evidence collection; they must remain release-blocking until real evidence is supplied, reviewed, fresh, and linked to the required acceptance files.

## Artifact

- Generator: `scripts/ops/security_verification/generate_production_blocker_evidence_packets.py`
- Output: `security_ir_artifacts/production/blocker-evidence-packets.json`
- Source bridge: `security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json`

## Packet Semantics

Each packet records:

- blocked task ID and title
- owner placeholder
- freshness requirement
- human-review requirement
- source, environment, runtime, and solver evidence slots
- required evidence text from the Xaman-to-production bridge
- expected acceptance files
- related Xaman blockers

The generated packets use:

- `status: missing_production_evidence`
- `release_acceptable: false`

That is intentional. A packet cannot become release-acceptable merely because it exists.

## Regeneration

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/generate_production_blocker_evidence_packets.py \
  --out security_ir_artifacts/production/blocker-evidence-packets.json
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_blocker_evidence_packets.py -q
```

## Release Policy

Production release remains blocked until every packet has:

- assigned owner
- fresh collection and expiry metadata
- human review
- concrete production source/environment/runtime/solver references as required
- all acceptance files present and validated
