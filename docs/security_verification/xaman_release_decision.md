# Xaman Release Decision

Task: `PORTAL-CXTP-075`

Decision: `blocked-production`

The Xaman source-corpus assurance packet is not release-ready for production.
The decision follows the frozen policy in
`docs/security_verification/production_release_decision_policy.md`: only a
`prove` outcome may be consumed as secure for blocking or high-risk claims, and
every non-`prove` outcome fails closed.

## Bound Packet

- Packet: `security_ir_artifacts/corpora/xaman-app/assurance-packet.json`
- Packet CID: `bafkreigzheeseiw36a5rqy3aggw4ia5gdkmzxlcmvmlnfluomr67ssjhzq`
- Model CID: `bafkreicugppxuacf5kxjsor7lqhwa3y44rrbsetiid2e65utlwgyablr5e`
- Corpus commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest digest: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`

## Gate Result

| Gate | Result | Release effect |
| --- | --- | --- |
| Blocking/high Xaman claims | 0 of 9 are `PROVED` | Blocks release |
| Assumptions | 12 of 20 remain `BLOCKING` | Blocks release |
| SMT differential | 9 blocked, 0 proved, no Z3/CVC5 disagreements | No release unblock |
| Disproof suite | Expected counterexamples archived, `scenario_failures: 0` | Evidence retained |
| TLA workflow | Apalache unavailable, 10 properties blocked | Blocks release |
| Protocol model | Tamarin and ProVerif unavailable, 9 properties blocked | Blocks release |
| Proof consumer | Receipt binding invariant fixture passes | Does not unblock release |
| Runtime traces | Real-device release-window traces absent | Blocks release |

## Blocking Conditions

The release remains blocked by:

- unaccepted assumptions for native vault confidentiality, passcode/KDF
  protection, biometric binding, third-party signing correctness, backend
  payload single-use and authorization, native/OS intake integrity, deployed
  network equivalence, XRPL validation semantics, XRPL server correctness,
  external multisign coordination, deployed runtime equivalence, and proof
  receipt CID or signature validation;
- no accepted `PROVED` packet for any blocking or high-risk Xaman claim;
- missing Apalache, ProVerif, and Tamarin proof lanes;
- absent real-device runtime traces and absent binary/backend/runtime
  equivalence evidence.

## Required Promotion Evidence

A future release decision can become eligible only after all of the following
are bound into a fresh packet:

- every blocking and high-risk claim has an accepted `PROVED` outcome;
- all blocking assumptions are evidenced, accepted, current, and bound to the
  release packet;
- Apalache and at least one accepted symbolic protocol prover lane are
  installed, rerun, and recorded with accepted solver output;
- proof receipts or trusted signatures validate model CID, claim ID, report
  CID, solver identity, assumptions, reviewed evidence, corpus commit, and
  fresh environment probe;
- release-window iOS and Android real-device traces cover payload intake,
  review, auth, signing, rejection, expiration, network binding, and broadcast;
- production binary, native module, backend deployment, node configuration, and
  source commit equivalence evidence are reviewed and current.

Until those conditions are met, production consumers must report
`blocked-production` and must not downgrade any blocker to a warning or manual
approval state.

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_assurance_packet.py -q
```
