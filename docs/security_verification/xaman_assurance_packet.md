# Xaman Assurance Packet

Task: `PORTAL-CXTP-075`

This packet is the fail-closed assurance bundle for the reviewed Xaman source
corpus. It aggregates the model CID, pinned corpus commit, source manifest,
environment probe, proof reports, disproof reports, solver matrix, runtime
trace report, assumptions, open blockers, and release decision into:

`security_ir_artifacts/corpora/xaman-app/assurance-packet.json`

## Packet Identity

- Schema: `xaman-assurance-packet/v1`
- Artifact CID: `bafkreigzheeseiw36a5rqy3aggw4ia5gdkmzxlcmvmlnfluomr67ssjhzq`
- Model CID: `bafkreicugppxuacf5kxjsor7lqhwa3y44rrbsetiid2e65utlwgyablr5e`
- Corpus commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest aggregate SHA-256: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`
- Environment probe: `security_ir_artifacts/corpora/xaman-app/environment-probe.json`

## Bundled Evidence

The packet binds these artifact lanes:

| Lane | Artifact |
| --- | --- |
| Source manifest | `security_ir_artifacts/corpora/xaman-app/source-manifest.json` |
| Source coverage | `security_ir_artifacts/corpora/xaman-app/source-coverage.json` |
| Security model | `security_ir_artifacts/corpora/xaman-app/security-model-ir.json` |
| Claims and assumptions | `security_ir_artifacts/corpora/xaman-app/security-claims.json` |
| SMT manifest | `security_ir_artifacts/corpora/xaman-app/smtlib/manifest.json` |
| Z3/CVC5 differential | `security_ir_artifacts/corpora/xaman-app/proof-reports/z3-cvc5-differential.json` |
| Disproof vectors | `security_ir_artifacts/corpora/xaman-app/disproof-vectors.json` |
| Counterexamples | `security_ir_artifacts/corpora/xaman-app/counterexample-report.json` |
| TLA+/Apalache workflow | `security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json` |
| Tamarin/ProVerif protocol | `security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json` |
| Proof consumer invariants | `security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json` |
| Runtime traces | `security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json` |

## Evidence Summary

- Critical claims: 9 blocking or high-risk claims.
- Proved critical claims: 0.
- Assumptions: 20 total, 8 evidenced and 12 blocking.
- SMT differential: 9 claims classified as blocked, 0 proved, 0 solver disagreements.
- Disproof suite: 6 expected counterexamples and 2 explicitly blocked vectors, with `scenario_failures: 0`.
- TLA workflow: 10 modeled properties blocked because Apalache is unavailable.
- Protocol model: 9 modeled properties blocked because Tamarin and ProVerif are unavailable.
- Runtime traces: 6 source/e2e traces and 20 monitor facts, but 0 real-device release-window traces.
- Open blockers: 17 total, covering blocking assumptions, proof gaps, missing solvers, and runtime equivalence.

## Solver Matrix

The configured environment has `z3`, `cvc5`, `python`, `node`, `npm`, and
`typescript` available. The packet also records independent solver blockers
for `apalache`, `proverif`, and `tamarin-prover`; those lanes cannot be
accepted as proved until the solvers are installed and the corresponding
reports are regenerated.

## Decision

The packet decision is `blocked-production`.

This is intentional and fail-closed. The reviewed corpus establishes useful
source-backed facts and negative fixtures, but it does not provide a production
release proof because blocking assumptions remain open, temporal and symbolic
protocol solvers are missing, proof outcomes are not `PROVED`, and real-device
runtime equivalence evidence is absent.

## Regeneration And Validation

Validate the packet with:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_assurance_packet.py -q
```

The test regenerates `assurance-packet.json` from the bound inputs and checks
the artifact CID, source commit, model CID, proof/disproof/runtime bundle,
solver matrix, open blockers, assumptions, and fail-closed release decision.
