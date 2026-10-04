# Xaman To Production Blocker Bridge

Task: `PORTAL-CXTP-076`

This bridge converts the Xaman assurance packet into the production evidence tasks that must be completed before `PORTAL-CXTP-077` through `PORTAL-CXTP-084` can move. It is machine-readable input for the supervisor; it is not release approval.

## Artifact

- Bridge: `security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json`
- Source packet: `security_ir_artifacts/corpora/xaman-app/assurance-packet.json`

## Mapped Production Tasks

The bridge covers:

- `PORTAL-CXTP-077`: production environment evidence.
- `PORTAL-CXTP-078`: deployed wallet, exchange, API, and policy source inventory.
- `PORTAL-CXTP-079`: reviewed production `SecurityModelIR` candidate.
- `PORTAL-CXTP-080`: required production domains and claim minimums.
- `PORTAL-CXTP-081`: production fail-closed proof baseline.
- `PORTAL-CXTP-082`: production disproof and mutation suite.
- `PORTAL-CXTP-083`: production runtime trace evidence.
- `PORTAL-CXTP-084`: production blockers and handoff checklist.

## Current Decision

The bridge is generated successfully, but production release remains blocked:

- `overall_status: ready_blocker_bridge_generated`
- `security_decision: PRODUCTION_BLOCKERS_MAPPED_RELEASE_REMAINS_BLOCKED`
- `production_release_blocked: true`

## Supervisor Policy

Keep `PORTAL-CXTP-077` through `PORTAL-CXTP-084` blocked until each task's acceptance files exist and validate. The bridge lists the evidence expected for each blocked task, including production environment profile, source inventory, production IR, claim gate, proof baseline, disproof suite, runtime traces, and release handoff checklist.
