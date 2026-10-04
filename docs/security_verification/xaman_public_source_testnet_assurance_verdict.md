# Xaman Public-Source/Testnet Assurance Verdict

Task: `PORTAL-CXTP-151`

Verdict: `DISPROVED`

**This is not a production or vendor-release security decision. It is bounded to reviewed public-source and XRPL Testnet verifier evidence and cannot approve, certify, reject, or reproduce the production Xaman vendor release.**

## Bound Artifacts

- Bundle: `security_ir_artifacts/corpora/xaman-app/testnet/public-source-testnet-assurance-bundle.json`
- Bundle CID: `bafkreiakkn2vkylh7352yoibgcldovczyhwnald4jw5xwnm5fnnrmtktwu`
- Verdict: `security_ir_artifacts/corpora/xaman-app/testnet/public-source-testnet-assurance-verdict.json`
- Verdict CID: `bafkreig2neh46ey766rm6ndlum42ynewtbcqqjvjqonygpzqis24muegpy`
- Model CID: `sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43`

## Basis

- Public source: `BLOCK_PUBLIC_SOURCE_ASSESSMENT_NOT_RELEASE_APPROVAL`; production release approval is `False`.
- Public Testnet build: `BLOCK_PUBLIC_TESTNET_BUILD_REPRODUCTION_NOT_VENDOR_RELEASE_EQUIVALENT`; vendor-release equivalent is `False`.
- Solver portfolio: `BLOCK_TESTNET_ASSURANCE_SOLVER_PORTFOLIO_COUNTEREVIDENCE` with status `non_secure_with_counterevidence`.
- Runtime conformance: `BLOCK_TESTNET_ASSURANCE_RUNTIME_CONFORMANCE_GAPS` with status `blocked_testnet_runtime_conformance`.
- Adversarial fuzzing: `25` minimized counterexamples are bound.

## TESTNET_SCOPE_ASSURED Gate

- `all_required_claims_have_current_reviewed_source_evidence`: `True`
- `all_required_claims_have_current_reviewed_runtime_evidence`: `False`
- `all_required_claims_have_required_solver_results`: `False`
- `no_fuzz_counterexamples_for_required_claims`: `False`
- `no_active_not_modeled_boundaries`: `False`
- `no_disproof_counterevidence`: `False`
- `testnet_scope_assured_allowed`: `False`

## Blockers

- `SOLVER_PORTFOLIO_COUNTEREVIDENCE` severity `disproof` from `security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-report.json` count `12`.
- `ADVERSARIAL_FUZZ_COUNTEREXAMPLES` severity `disproof` from `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json` count `25`.
- `PUBLIC_SOURCE_KNOWN_COUNTEREXAMPLES` severity `disproof` from `security_ir_artifacts/corpora/xaman-app/public-source-assessment.json` count `7`.
- `RUNTIME_CONFORMANCE_ASSURANCE_BLOCKS` severity `blocking` from `security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-report.json` count `17`.
- `REQUIRED_CLAIMS_NOT_TESTNET_SCOPE_ASSURED` severity `blocking` from `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json` count `12`.
- `ACTIVE_NOT_MODELED_BOUNDARIES` severity `not_modeled` from `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json` count `8`.
- `PUBLIC_BUILD_NOT_VENDOR_RELEASE_EQUIVALENT` severity `scope` from `security_ir_artifacts/corpora/xaman-app/testnet/public-build-reproduction.json`.
- `PUBLIC_SOURCE_NOT_PRODUCTION_RELEASE_APPROVAL` severity `scope` from `security_ir_artifacts/corpora/xaman-app/public-source-assessment.json`.

## Required Evidence Or Owner Action

- `formal-methods`: Resolve fail-closed Z3/CVC5, Tamarin/ProVerif, Rocq/Coq, and fuzz-consumption counterevidence for every required Testnet claim. Source: `security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-report.json`.
- `assurance-fuzzing`: Either fix the model/evidence so minimized counterexamples no longer trigger required claims or retain DISPROVED. Source: `security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json`.
- `runtime-verification`: Provide reviewed, redacted Testnet lifecycle evidence for every required runtime path, including cancellation, expiry, replay, cryptographic-signing boundary, submit result, and ledger finality. Source: `security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-report.json`.
- `modeling-review`: Replace active NOT_MODELED boundaries with reviewed modeled claims or keep NOT_MODELED/BLOCKED rather than TESTNET_SCOPE_ASSURED. Source: `security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json`.
- `mobile-build-security`: Keep public-source Testnet verifier evidence separated from vendor release equivalence unless vendor-authorized release provenance is supplied. Source: `security_ir_artifacts/corpora/xaman-app/testnet/public-build-reproduction.json`.
- `release-security`: Do not use this public-source/Testnet verdict as production release approval. Source: `security_ir_artifacts/corpora/xaman-app/public-source-assessment.json`.

## Decision Rule

TESTNET_SCOPE_ASSURED is permitted only after every required claim has current human-reviewed source evidence, current reviewed runtime evidence, all applicable required solver results accepted with recorded versions, command digests, timeouts, and reviewer status, no fail-closed solver or fuzz counterevidence, and the non-production/vendor-release boundary is preserved.

Allowed verdict values remain exactly `TESTNET_SCOPE_ASSURED`, `DISPROVED`, `UNKNOWN`, `NOT_MODELED`, or `BLOCKED`.
