# Xaman XRPL Transaction Model

Task: `PORTAL-CXTP-066`

This model records reviewed XRPL transaction semantics from the pinned Xaman React Native source corpus. The machine-readable artifact is `security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json`.

## Source Boundary

- Corpus: `xaman-app`
- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Manifest aggregate SHA-256: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`
- Coverage artifact: `security_ir_artifacts/corpora/xaman-app/source-coverage.json`

This artifact models client-side semantics from the reviewed TypeScript source. It does not prove XRPL consensus, complete amendment coverage, node honesty, runtime service freshness, or deployed binary equivalence.

## Common Transaction Fields

`src/common/libs/ledger/transactions/common.ts` defines the common transaction surface. The model treats `TransactionType`, `Account`, `Sequence`, and `LastLedgerSequence` as required common fields. It also records optional common fields that affect safety claims: `Fee`, `Memos`, `Signers`, `NetworkID`, `TicketSequence`, signing public key fields, and hook parameters.

`TransactionFactory` reads `TransactionType`, rejects missing transaction types, dispatches to matching transaction classes, and otherwise creates `FallbackTransaction`. Ledger-sourced transactions are not allowed to receive the signing mixin.

## Payment Semantics

The `Payment` class requires `Amount` and `Destination`, models optional destination tag, invoice ID, pathfinding fields, `SendMax`, `DeliverMin`, and credentials, and derives delivered amount from metadata. Native delivered amounts are converted from drops to the network native asset.

Payment validation rejects missing or zero amounts, checks native payments against fresh available balance, checks issued-currency destination trustlines, checks issuer freezes, checks sender IOU balances, and checks issuer obligation limits when the source account is the issuer. The model records that path payments skip these client-side checks.

## Issued Currency And Trustlines

Issued-currency semantics are modeled for Payment and TrustSet boundaries. `TrustSet` exposes `LimitAmount`, currency, issuer, and numeric limit, but its validation function is a TODO pass-through. That gap is marked `NOT_MODELED` and must be treated as blocking for claims that depend on TrustSet user-intent validation.

`OfferCreate` similarly models `TakerPays`, `TakerGets`, rate, expiration, offer ID, and offer-status inference, but its validation is also a TODO pass-through.

## Multisign

`SignerListSet` models `SignerQuorum` and `SignerEntries` through the `SignerEntries` codec. Its validation is a TODO pass-through, so signer quorum and signer-entry safety are not proved by this artifact. `Sign.mixin.ts` also records that multisign skips the normal `prepare` path.

## Network And Signing Bounds

`Sign.mixin.ts` is the signing boundary for fee, sequence, ledger-window, and network constraints. It requires an account parameter, rejects already-signed transactions, rejects unsupported transaction types for the current network definitions, requires a fee before prepare, sets account sequence when missing, populates `LastLedgerSequence`, writes `NetworkID` only for non-legacy network IDs greater than 1024, rejects aborted transactions, and requires signed blob, signer public key, and sign method from the vault callback.

These checks depend on `LedgerService` and `NetworkService`. Their freshness, endpoint authenticity, and runtime configuration are `NOT_MODELED` here.

## Memo And Amount Parsing

`AmountParser` normalizes amounts through `BigNumber`, rejects fractional drops, converts drops to native units by dividing by 1,000,000, and converts native units to drops by multiplying by 1,000,000 and rounding to whole drops.

`MemoParser` treats long hex-like values as `application/x-binary` reference memos and otherwise hex-encodes `text/plain` description memos. Binary memo decode preserves raw memo data.

## Broadcast Boundary

The broadcast boundary is the XRPL `submit` request with a signed `tx_blob`. `SubmitResponse` fields are preliminary node state: `accepted`, `applied`, `broadcast`, `kept`, and `queued`, plus sequence and ledger-index values. `Sign.mixin.ts` locally blocks submission without a signed blob, blocks duplicate submit attempts, and sets `fail_hard` for `AccountDelete`.

This is not finality. XRPL consensus, validated-ledger inclusion, queue behavior, mempool behavior, and honest peer-server broadcast are `NOT_MODELED`.

## NOT_MODELED Gaps

The artifact marks these blocking gaps:

- `TrustSet`, `OfferCreate`, and `SignerListSet` validations resolve without semantic checks.
- Complete XRPL transaction-class and amendment coverage is not established.
- `LedgerService` and `NetworkService` freshness, endpoint authenticity, and runtime configuration are not proved.
- XRPL consensus, finality, queue, mempool, and peer broadcast behavior are not proved.
- Deployed runtime equivalence to the reviewed source commit is not proved.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_model.py -q
```

The tests validate manifest-bound evidence hashes, required modeled categories, payment and trustline semantics, signing and network guards, memo and amount parsing, submit boundaries, explicit `NOT_MODELED` gaps, and documentation coverage.
