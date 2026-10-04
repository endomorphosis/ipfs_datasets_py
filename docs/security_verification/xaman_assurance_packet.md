# Xaman Assurance Packet

Task: `PORTAL-CXTP-075`

The assurance packet is the roll-up artifact for the Xaman theorem-prover work. It collects the reviewed source facts, SecurityModelIR, solver outputs, disproof vectors, runtime trace status, and proof-consumer kernel evidence into a single release decision input.

## Artifact

- Packet: `security_ir_artifacts/corpora/xaman-app/assurance-packet.json`
- Bound model CID: `sha256:316ead1268fb192641ece96ef255e92922b93623d6f4b1057dc56a2cec711c8d`

## Included Evidence

The packet indexes:

- Xaman source manifest and source coverage.
- Wallet authentication facts.
- Payload lifecycle facts.
- XRPL transaction facts.
- Security claims and Xaman `SecurityModelIR`.
- Z3/CVC5 SMT differential report.
- Counterexample/disproof report.
- TLA/Apalache workflow report.
- Tamarin/ProVerif protocol projection report.
- Runtime trace report.
- Lean proof-consumer kernel report.

## Result

The packet is intentionally fail-closed:

- `overall_status: blocked`
- `release_decision: reject_release`
- `security_decision: BLOCK_XAMAN_RELEASE_ASSURANCE_PACKET`

The packet does not prove Xaman secure. It records that the current evidence is enough to identify blocked assumptions, counterexamples, missing runtime evidence, and unavailable solver lanes.

## Main Blockers

- Unresolved Xaman assumptions across blocking/high claims.
- SMT differential lane blocks all claims because assumptions remain uncleared.
- Counterexamples exist in the disproof suite.
- Some disproof vectors are blocked by missing evidence.
- Runtime equivalence lacks real-device traces.
- Apalache has not run.
- Tamarin/ProVerif have not run.
- The Lean proof-consumer kernel is checked but not integrated into production.

## Next Evidence

The packet points the production lane toward:

- `PORTAL-CXTP-077`: production environment profile.
- `PORTAL-CXTP-078`: production source inventory.
- Real-device runtime trace bundle.
- Solver installation or explicit scoping for Apalache, Tamarin, ProVerif, and Coq.
- Production integration evidence for the Lean proof-consumer kernel.
