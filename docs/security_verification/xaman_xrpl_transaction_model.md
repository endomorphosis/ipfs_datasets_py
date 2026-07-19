# Xaman XRPL Transaction Model

Tasks: `PORTAL-CXTP-066`, `PORTAL-CXTP-146`

This model records reviewed XRPL transaction semantics from the pinned Xaman
React Native source corpus. The facts artifact is
`security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json`; the
coverage artifact is `security_ir_artifacts/corpora/xaman-app/xrpl-transaction-coverage.json`.

## Proof Boundary

The coverage decision is `RECORD_GAP_OR_COUNTEREXAMPLE_NEVER_PROOF`: each
reachable public flow is source-modeled, explicitly rejected, or retained as a
blocking coverage gap. This is not a proof of XRPL consensus, node honesty,
runtime freshness, native vault signing, deployed-binary equivalence, or
production release safety.

## Constraint Coverage

- `TrustSet`: `EXPLICITLY_REJECTED_FOR_PROOF` - TrustSet class fields are modeled, but validation resolves without semantic checks; TrustSet user-intent safety is rejected for proof.
- `OfferCreate`: `EXPLICITLY_REJECTED_FOR_PROOF` - OfferCreate taker amount and rate presentation is modeled, but validation resolves without semantic checks; offer safety is rejected for proof.
- `SignerListSet`: `EXPLICITLY_REJECTED_FOR_PROOF` - SignerListSet quorum and entries are decoded, but validation resolves without semantic checks; signer-list safety is rejected for proof.
- `payment`: `MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS` - Payment fields, native amount checks, issued-currency trustline checks, issuer freeze checks, and issuer obligation checks are modeled from source.
- `issued_currency`: `PARTIALLY_MODELED_AND_PARTIALLY_REJECTED` - Issued-currency Payment trustline and issuer checks are modeled; TrustSet and OfferCreate issued-currency semantics remain rejected because their validators are TODO pass-throughs.
- `destination_tag`: `MODELED_FIELD_PRESERVATION` - Payment exposes DestinationTag as an optional field. The source-backed model preserves the field but does not prove exchange-specific tag policy correctness.
- `fee`: `MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS` - Signing requires Fee before prepare and balance mutation display deducts the fee, but fee freshness and server fee policy are outside the client proof.
- `sequence`: `MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS` - The model records required Sequence/LastLedgerSequence fields and SignMixin sequence population, while ledger freshness remains an explicit gap.
- `multisign`: `EXPLICITLY_REJECTED_FOR_PROOF` - Common Signers and SignerListSet fields are modeled, and SignMixin records that multisign skips prepare; signer-list semantic safety is rejected.
- `memo`: `MODELED` - Memo parsing distinguishes text/plain descriptions from application/x-binary reference memos and preserves binary memo data.
- `network`: `MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS` - Signing rejects unsupported transaction types for current network definitions and writes NetworkID only for non-legacy network IDs greater than 1024.
- `canonicalization`: `EXPLICITLY_REJECTED_FOR_FULL_XRPL_BINARY_PROOF` - Amount and memo normalization are modeled, but XRPL binary canonicalization and the vault-produced signed blob are not proved by the public TypeScript evidence.

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_coverage.py -q
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/build_xaman_xrpl_transaction_coverage.py
```
