# Xaman XRPL Testnet Assurance Verdict

Task: `PORTAL-CXTP-139`

Verdict: `TESTNET_SCOPE_NOT_SECURE`

This is not a production-security result. It covers only the reviewed XRPL Testnet verifier APK, emulator trial, formalized model, solver reports, and fuzz artifacts bound in the Testnet assurance bundle.

## Bound Artifacts

- Bundle: `security_ir_artifacts/corpora/xaman-app/testnet/assurance-bundle.json`
- Bundle CID: `bafkreidstcp4wwsnzjbb3y2bplhtpkvn5ivpoclq23zn4a4oa57pascamm`
- Verdict: `security_ir_artifacts/corpora/xaman-app/testnet/assurance-verdict.json`
- Verdict CID: `bafkreihqhyoavkcefrlwwdal3qph4wxmyk4ld2wptohltre2luz36dhakq`
- Model CID: `sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43`

## Basis

- SMT Z3/CVC5: `BLOCK_TESTNET_ASSURANCE_COUNTEREXAMPLES` with `12` counterexample classifications.
- Apalache: `BLOCK_TESTNET_ASSURANCE_UNRESOLVED_CONCURRENCY_ASSUMPTIONS` with `2` unresolved required assumptions.
- Protocol lane: `BLOCK_TESTNET_ASSURANCE_PROTOCOL_SOLVER_LANE_UNAVAILABLE`; blockers are `PROVERIF_MODEL_MISSING, TAMARIN_CHECK_NOT_RUN`.
- Lean: `LEAN_TESTNET_KERNEL_CHECKED_FORMALIZED_INVARIANTS_ONLY` for formalized invariants only.
- Coq: `BLOCK_TESTNET_ASSURANCE_INDEPENDENT_COQ_KERNEL_MISSING`.
- Fuzzing: `TESTNET_FUZZ_CAMPAIGNS_PASSED_BOUNDED_GENERATED_COVERAGE` with bounded generated coverage.

## Required Evidence Or Owner Action

- `security-verification` for `xaman-testnet-assumption:testnet-verifier-evidence-is-not-production-evidence`: reviewer signoff and replacement evidence bundle Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `ledger-verification` for `xaman-testnet-assumption:testnet-network-binding-is-verifier-only`: production runtime network trace; endpoint authenticity model; fresh server_info evidence Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `wallet-verification` for `xaman-testnet-assumption:fresh-account-boundary-is-verifier-attested`: reviewed wallet provenance trace with allowed account identifiers redacted by policy Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `runtime-verification` for `xaman-testnet-assumption:reviewed-ui-event-is-operator-attested`: reviewer signoff and replacement evidence bundle Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `security-verification` for `xaman-testnet-assumption:redacted-categorical-evidence-only`: reviewer signoff and replacement evidence bundle Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `payload-verification` for `xaman-testnet-assumption:raw-payload-material-excluded`: reviewer signoff and replacement evidence bundle Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `wallet-key-management` for `xaman-testnet-assumption:native-vault-and-biometric-security-not-proved`: native vault audit; signature-byte binding trace; cryptographic signing proof Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `wallet-transaction-signing` for `xaman-testnet-assumption:raw-signature-and-transaction-blob-excluded`: native vault audit; signature-byte binding trace; cryptographic signing proof Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `ledger-verification` for `xaman-testnet-assumption:xrpl-broadcast-finality-not-proved`: raw-broadcast-safe digest evidence; XRPL validated-ledger inclusion proof; finality model Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `payload-backend-verification` for `xaman-testnet-assumption:backend-replay-single-use-not-exercised`: duplicate-submit negative trace; backend atomic single-use evidence; expiration enforcement trace Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `runtime-verification` for `xaman-testnet-assumption:decline-cancel-expiry-not-exercised`: reviewed decline trace; reviewed cancel trace; reviewed expiry trace Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `release-security` for `xaman-testnet-assumption:deployed-runtime-equivalence-not-proved`: production build provenance; real-device trace bundle; runtime equivalence review Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `mobile-build-security` for `xaman-testnet-assumption:native-firebase-packaging-boundary`: native Firebase-free APK proof or corrected label Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `formalization-review` for `xaman-testnet-assumption:source-derived-facts-must-be-reviewed`: reviewed source-to-model trace map for every source-derived fact Source: `security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json`.
- `protocol-verification`: Add a reviewed ProVerif projection for the Testnet payload protocol.; Run ProVerif with pinned executable/version/digest and attach the accepted report. Source: `security_ir_artifacts/corpora/xaman-app/testnet/protocol/protocol-report.json`.
- `protocol-verification`: Run the pinned Tamarin model against an accepted Maude runtime.; Record the command, version, executable digest, and accepted lemma results. Source: `security_ir_artifacts/corpora/xaman-app/testnet/protocol/protocol-report.json`.
- `formal-methods`: Provide security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.v.; Run coqc and bind the checked independent-kernel artifact to the Testnet model CID. Source: `security_ir_artifacts/corpora/xaman-app/testnet/coq-coverage-decision.json`.

## Decision Rule

Advance only after all blocking owner actions are satisfied, the model CID is regenerated, Z3/CVC5 no longer emit counterexamples for required claims, Tamarin/ProVerif and required Coq evidence are accepted, and a new bundle is issued with the same non-production scope statement.

Allowed verdict values remain exactly `TESTNET_SCOPE_ASSURED`, `TESTNET_SCOPE_NOT_SECURE`, or `TESTNET_SCOPE_INCONCLUSIVE`.
