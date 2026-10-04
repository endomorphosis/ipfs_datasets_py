# Xaman XRPL Testnet Theorem-Prover Assurance Plan

Target corpus: `XRPL-Labs/Xaman-App` at commit `942f43876265a7af44f233288ad2b1d00841d5fa`.

This plan evaluates the React Native wallet in a verifier-only XRPL Testnet scope. It can establish that specific, modeled claims hold or produce counterexamples under declared assumptions. It cannot establish that the production Xaman wallet, its backend, the XRPL network, or all possible device inputs are secure.

## Decision Vocabulary

- `PROVED`: the stated claim holds for the immutable SecurityModelIR, solver version, evidence digests, and assumptions recorded by that run.
- `DISPROVED`: a solver, model checker, or reviewed runtime trace produced a counterexample. The affected Testnet claim is not secure.
- `UNKNOWN` or `NOT_MODELED`: insufficient coverage, timeout, unavailable solver, or absent semantics. This is a blocker, not a pass.
- `TESTNET_SCOPE_ASSURED`: all required Testnet claims have reviewed evidence and a permitted proof outcome. It is not a production-security decision.

## Verified Starting Point

- The corpus source manifest and environment probe bind the React Native, Android, iOS, TypeScript, and Detox/e2e surface to the pinned commit.
- The Testnet selection verifier has established `TESTNET`, one reviewed public endpoint, and an XRPL `server_info` response with `network_id: 1`; it stores only categorical values and digests.
- The Firebase-disabled verifier and DuckDB mock capture redacted JavaScript-stub telemetry. Native Firebase remains packaged, so the APK is labeled `firebase_js_stubbed_only` rather than fully Firebase-disabled.
- The active prover executes bounded Z3 claims. Lean is available for kernel checks. Apalache, Tamarin, ProVerif, Coq, and configured Leanstral remain absent or incomplete coverage lanes.

## Assumptions To Freeze And Review

1. **Source and build**: commit, lockfiles, native dependency digests, Metro/Gradle overlays, APK digest, and a fresh emulator image are immutable for each run.
2. **Testnet trust**: the endpoint allow-list is exactly the reviewed Testnet set, `network_id` is `1`, and the Testnet account is fresh and never imported from production material.
3. **Wallet boundary**: secrets, seeds, addresses, raw payloads, transaction blobs, credentials, and production accounts never enter reports, prompts, DuckDB, or task artifacts.
4. **Runtime boundary**: a redacted trace proves only its observed operation, device, build, and collection window. It does not establish native equivalence or backend behavior outside the trace.
5. **Formalization boundary**: source extraction is heuristic until a reviewer binds every claim fact to specific source and runtime evidence.
6. **Solver boundary**: versions, executable digests, timeout, model CID, command, and proof/counterexample CID are evidence. Missing or disagreeing solvers fail closed.

## Testnet Claim Matrix

| Claim family | Required Testnet evidence | Formal method | Failure outcome |
| --- | --- | --- | --- |
| Network binding | Fresh profile, network key, endpoint digest, `server_info` digest | SecurityModelIR + Z3/CVC5 | Wrong network/endpoint is a counterexample |
| Account provenance | Fresh Testnet-only account boundary | Runtime trace + review | Missing or imported-account evidence blocks |
| Payload review and auth | Redacted payload-review, auth, decline, and expiry events | TLA+/Apalache and Lean obligations | Bypass/replay race is a counterexample |
| Signing safety | Reviewed preconditions, vault/auth state, canonical signing intent | Z3/CVC5 + Lean kernel | Signing after freeze or without review is a counterexample |
| XRPL submission | Network-bound submit outcome, no raw transaction data | Trace-to-IR and protocol model | Cross-network/replay or unbound submit blocks |
| Remote payload protocol | Correlation-safe request/resolve/cancel/expiry behavior | Tamarin or ProVerif | Replay, substitution, or authentication failure blocks |
| State and concurrency | Resolution, cancellation, retries, network changes | TLA+/Apalache | Reachable unsafe state blocks |
| Input robustness | Parser, schema, and registered adversarial mutation grammar | Bounded exhaustive and seeded fuzzing | Harness failure or missed expected disproof blocks |

## Execution Order

1. Complete the fresh-device Testnet trial using only the verifier APK and a Testnet-only account boundary.
2. Capture a redacted transaction-lifecycle trace: network selection, review, authentication, signing decision, submit attempt/result, rejection/cancel/expiry, and reconnect/network-change paths. No secrets or transaction material are retained.
3. Project the trace into a reviewed Testnet SecurityModelIR claim map. Every unrepresented path becomes `NOT_MODELED`.
4. Lock a reproducible Testnet proof worker and run Z3/CVC5 differential checks on the same model CID. Preserve all reports and counterexamples.
5. Run bounded-exhaustive mutation fuzzing for the registered input grammar, then add property fuzzing only after the trace-to-IR schemas are reviewed.
6. Provision optional solvers only where the approved threat model requires them: Apalache for concurrency, Tamarin/ProVerif for protocol authentication and replay, and Coq for an independently checked kernel when Lean evidence is insufficient.
7. Use Leanstral only to propose proof terms, model edits, or counterexample hypotheses. Lean, Z3, CVC5, Apalache, Tamarin, ProVerif, or Coq remain the acceptance authorities.
8. Assemble a Testnet-scoped evidence bundle and issue either a qualified Testnet assurance verdict or a precise non-secure result with counterexamples and remaining assumptions.

## Solver Coverage And Dependencies

- **Z3**: required current baseline for SecurityModelIR claims.
- **CVC5**: required differential SMT runner once the Testnet trace model is frozen; runner wiring, binary provenance, and disagreement handling must be demonstrated.
- **Lean**: available. Use it to check durable invariants and proof-consumer checks, not to replace device evidence.
- **Apalache**: install and pin only for concurrent payload-resolution, cancellation, retry, and network-switch state machines.
- **Tamarin/ProVerif**: install and pin only for remote payload/request authentication, replay, and channel-binding models.
- **Coq**: decide explicitly whether an additional kernel is required after reviewing Lean coverage; absence remains a documented coverage gap.
- **Leanstral**: configure a reproducible model route or locally pinned weights, prompt archive, and candidate-proof audit. Generated text is untrusted until an independent checker accepts it.

## Evidence Package Requirements

Each Testnet proof/disproof run must include the corpus commit, model CID, APK/build digest, emulator/device profile digest, solver executable/version/digest, command, seed and fuzz scope, input/redaction policy, endpoint decision digest, trace digest, outcomes, counterexamples, reviewer, and expiry date. A pass must remain invalid if any required file is missing, stale, unreviewed, or inconsistent.

## Non-Claims

This plan does not authorize handling real assets, importing a production wallet, publishing Testnet credentials, or declaring production security. Testnet availability, `server_info`, Firebase-stub telemetry, fuzz coverage, and a green proof run are individually insufficient evidence of production security.
