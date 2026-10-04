# Xaman Counterexample Triage

Task: `PORTAL-CXTP-164`

The generated triage artifact is
`security_ir_artifacts/corpora/xaman-app/counterexample-triage.json`. It joins
the public-source disproof vectors, bounded fuzz attack mutations, XRPL
transaction coverage, and native-vault state-fuzz conditions so each retained
result has an explicit interpretation.

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/build_xaman_counterexample_triage.py
```

## Interpretation Rule

A model mutation, a proof-consumer control test, or a fuzz target-claim trigger
is not a product exploit. Every entry remains release-blocking until the
appropriate proof or runtime evidence exists, but the report does not claim a
confirmed Xaman vulnerability.

The classifications are:

- `SOURCE_SUPPORTED_COVERAGE_GAP`: public source supports a proof-coverage
  gap. `TrustSet`, `OfferCreate`, and `SignerListSet` remain proof-ineligible
  because their selected validation paths are explicitly incomplete.
- `BOUNDARY_MODEL_MUTATION`: an attack alters a model guard, such as review,
  authentication, account provenance, or network binding. Reproduce it against
  an unmodified reviewed runtime before escalating it beyond a model result.
- `PROOF_CONSUMER_CONTROL_MUTATION`: a mutation checks that stale or downgraded
  evidence cannot be promoted by the proof consumer.
- `EXTERNAL_EVIDENCE_REQUIRED`: client public source cannot establish backend
  single-use or deployed-runtime equivalence; collect an authorized contract or
  reviewed runtime/build evidence rather than infer it.
- `UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS`: replay, cancellation, expiry,
  reconnect, and ledger-finality mutations need self-hosted runtime evidence or
  an authorized backend contract.
- `SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION`: a source-bound state model exposes
  a recovery condition that needs reviewed fault injection on the unmodified
  Android and iOS verifier builds. It is not a product exploit or defect claim.

This triage preserves the fail-closed Testnet verdict. It does not remove a
counterexample, promote a claim, or make a product-security assertion.

For remediation prioritization and next-step lane mapping, use
`scripts/ops/security_verification/plan_gap_remediation_from_triage.py` to generate
`security_ir_artifacts/corpora/xaman-app/gap-remediation-matrix.json` and the
`docs/security_verification/xaman_gap_remediation_plan.md` plan artifact.
