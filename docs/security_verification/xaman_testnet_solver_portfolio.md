# Xaman Testnet Solver Portfolio

Task: `PORTAL-CXTP-147`

Model CID: `sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43`

Manifest: `security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-manifest.json`
Report: `security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-report.json`

This portfolio reconciles the public-source XRPL Testnet model across SMT, state, protocol, kernel, and fuzz-result lanes. It is not a production-security result.

## Decision

- Overall status: `non_secure_with_counterevidence`
- Security decision: `BLOCK_TESTNET_ASSURANCE_SOLVER_PORTFOLIO_COUNTEREVIDENCE`
- Claims: `12`
- Fail-closed claims: `12`
- Proof-promotable claims: `0`

## Lanes

- `z3_cvc5_differential`: `non_secure_with_counterexamples`; report `security_ir_artifacts/corpora/xaman-app/testnet/proof-reports/z3-cvc5-differential.json`; command digest `sha256:175199ee81f8ddf57ece6bc3ac8fe1abeabc3c1577eff5ef88d6fd5da511899a`; timeout `5.0` seconds; reviewer `human_reviewed`.
- `apalache_state`: `checked_with_unresolved_threat_model_gaps`; report `security_ir_artifacts/corpora/xaman-app/testnet/tla/apalache-report.json`; command digest `sha256:1c2c1aab5b33245cb3996d82d2fe736bc46ba7fa349e33dd02df15292ddf58b9`; timeout `120` seconds; reviewer `human_reviewed`.
- `tamarin_protocol`: `passed`; report `security_ir_artifacts/corpora/xaman-app/testnet/protocol/protocol-report.json`; command digest `sha256:e8bd558d02b8061c2306112f0731bcb0c7bf7d8313b6ed38a535d023e0746916`; timeout `120` seconds; reviewer `human_reviewed`.
- `proverif_protocol`: `passed`; report `security_ir_artifacts/corpora/xaman-app/testnet/protocol/protocol-report.json`; command digest `sha256:4330c0111b742171af8e63b847197de56cbd41c3af712c657114966019f144db`; timeout `120` seconds; reviewer `human_reviewed`.
- `lean_kernel`: `checked_with_scope_limits`; report `security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/lean-report.json`; command digest `sha256:b428d084bf966879f015e71a764dbe7120b2521f639733e1a99707b42956c27f`; timeout `90` seconds; reviewer `human_reviewed`.
- `rocq_kernel`: `independent_kernel_checked`; report `security_ir_artifacts/corpora/xaman-app/testnet/coq-coverage-decision.json`; command digest `sha256:79a62ca43991a324159219f58cd5f4735fecd28f0b05cb02d659bdcb09fb650a`; timeout `90` seconds; reviewer `not_recorded`.
- `fuzz_consumption`: `passed`; report `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json`; command digest `sha256:04cd219a67a297f421e79962da2656cb55774bf0b771e0ebd71828a85b1b7dc3`; timeout `300` seconds; reviewer `not_recorded`.

## Lane Result Counts

- `ACCEPTED`: `32`
- `COUNTEREXAMPLE`: `24`
- `INCOMPLETE`: `4`

## Claim Results

- `xaman-testnet-claim:network-binding-is-testnet-only` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreibtwsmmhc4asroia4srnmv67jvxcvje7ome5jcqrit4out2uyvdme`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, lean_kernel:ACCEPTED, rocq_kernel:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:account-provenance-is-fresh-testnet-only` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreicuv4uteepzr665xdmdtqhnczb7yybf2l7vqttc3fyblc2s7uwquu`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, lean_kernel:ACCEPTED, rocq_kernel:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:review-auth-sequence-observed` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreif663jqb2m6qwm7hqi2gt6hc7vwdmyltcpidw4r5cjxsopqw3vka4`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, lean_kernel:ACCEPTED, rocq_kernel:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreihmpsqszotmdfwqhx5zgsjk7zrw7mpbo7tb46vzmkozkq5a6tfltu`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:submission-ui-attempt-and-result-are-observed` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreidiwpmw2gq72edeowy3g6zwvph7k6zkpfuo2rdojqv4rsk4styciq`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, apalache_state:INCOMPLETE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:payload-intake-is-categorical-only` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreieiwsk4zwwgqybjvw5emnd4glxoxi4jegltxggd5nixrkicei4cxe`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:refusal-path-is-not-modeled` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreidvuaqae5dhvgfpupmfj3tuxaqven3vxu7iycrmppx3eukz7jnw3q`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:replay-controls-are-not-modeled` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreidcbeb2t7b4tryonl2uhwom2mcmk3sxamlecbdyaqfkmkpvradvqe`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, apalache_state:INCOMPLETE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:expiry-path-is-not-modeled` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreicuiak6tewvc2g6i3vaj2qg5esjextunbov3x2rjq72smt2vi3vsi`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, apalache_state:INCOMPLETE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:cancellation-path-is-not-modeled` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreigqwtat5jpvi35k6ayluc4h7xuvoqanw3dnqjht2e73k3kdmicegu`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, apalache_state:INCOMPLETE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreiejgseqs4qubnauceqwz23zifomwgqvgyzyqqqbg3l24h7v46xf6u`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.
- `xaman-testnet-claim:audit-redaction-boundary-is-preserved` -> `NON_SECURE_COUNTEREVIDENCE`. Evidence set `bafkreie2urqguj37avxo4wxtwgamw2emxb6gbdvurgivonsvwsj27abduq`. Lanes: z3_cvc5_differential:COUNTEREXAMPLE, tamarin_protocol:ACCEPTED, proverif_protocol:ACCEPTED, lean_kernel:ACCEPTED, rocq_kernel:ACCEPTED, fuzz_consumption:COUNTEREXAMPLE.

## Fail-Closed Policy

Every unavailable, missing, not-run, disagreeing, timeout, unknown, or counterexample lane is recorded as fail-closed for the applicable claim. Lanes outside a claim theory are recorded as `NOT_APPLICABLE` and are not consumed as proof evidence.

The current portfolio records SMT counterexamples for every frozen Testnet claim, unresolved Apalache and protocol assumptions, accepted bounded Tamarin/ProVerif/Lean/Rocq/Coq checks, and fuzz counterexamples consumed as blocking counterevidence. Accepted bounded lanes do not discharge assumptions, runtime-equivalence gaps, or counterexamples in other lanes.
