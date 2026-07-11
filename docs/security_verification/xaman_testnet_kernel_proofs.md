# Xaman Testnet Kernel Proofs

Task: `PORTAL-CXTP-136`

The Testnet proof-kernel artifacts are:

- Lean kernel: `security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.lean`
- Lean report: `security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/lean-report.json`
- Coq coverage decision: `security_ir_artifacts/corpora/xaman-app/testnet/coq-coverage-decision.json`

They are bound to the frozen Testnet model CID:

`sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43`

## Lean Scope

`XamanTestnet.lean` formalizes a small Boolean kernel for reviewed Testnet evidence:

- Testnet network boundary: `TESTNET`, network id `1`, and an allow-listed endpoint.
- Fresh-account boundary: fresh Testnet account evidence, no production import, and no retained account material.
- Reviewed lifecycle order: payload intake, review, auth, signing decision, submit attempt, and submit result in the reviewed order.
- Audit redaction boundary: no raw payload, no raw signature or transaction blob, and preserved redaction.

The kernel proves fail-closed rejection for counterexample or incomplete kernel results, non-modeled claim statuses, model-CID mismatch, missing frozen-model membership, unreviewed evidence, wrong network binding, production-account boundary failures, missing lifecycle steps, ordering failures, retained raw material, redaction failures, uncleared assumptions, missing runtime equivalence, and missing independent-kernel coverage.

This is evidence only about the predicates in `XamanTestnet.lean`. It does not prove native vault cryptography, raw payload semantics, backend single-use behavior, XRPL broadcast/finality, deployed runtime equivalence, all wallet inputs, or production Xaman security.

## Current Result

`lean-report.json` records:

- `overall_status: checked_with_scope_limits`
- `security_decision: LEAN_TESTNET_KERNEL_CHECKED_FORMALIZED_INVARIANTS_ONLY`
- `testnet_assurance_blocked: true`

The checked Lean claim scope covers only the modeled Testnet-scope claims for network binding, account provenance, review/auth sequencing, and audit redaction. Claims with `MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY` or `NOT_MODELED` status remain rejected for proof promotion by the Lean kernel.

## Coq Decision

The reviewed Testnet assurance plan requires an independent kernel when Lean-only evidence is insufficient for the final assurance lane. This task therefore records Coq as required independent-kernel coverage for Testnet assurance.

The current decision is:

- `decision: required_missing_artifact`
- `overall_status: coverage_gap_required_independent_kernel_missing`
- `security_decision: BLOCK_TESTNET_ASSURANCE_INDEPENDENT_COQ_KERNEL_MISSING`

`coqc` may be present on a verifier host, but there is no checked `security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.v` artifact. Missing Coq is therefore a declared coverage gap. This does not invalidate the checked Lean formalized invariant; it blocks any claim that the Testnet assurance bundle has independent Coq kernel coverage.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_kernel_proofs.py -q
test -f security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.lean
test -f security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/lean-report.json
test -f security_ir_artifacts/corpora/xaman-app/testnet/coq-coverage-decision.json
```
