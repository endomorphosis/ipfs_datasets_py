# Xaman XRPL Transaction Semantics Model

Task: `PORTAL-CXTP-066`

This model records reviewed XRPL transaction-semantics facts for the pinned Xaman React Native source corpus. The machine-readable artifact is `security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json`.

## Source Boundary

- Corpus: `xaman-app`
- Repository: `https://github.com/XRPL-Labs/Xaman-App`
- Commit: `942f43876265a7af44f233288ad2b1d00841d5fa`
- Manifest: `security_ir_artifacts/corpora/xaman-app/source-manifest.json`
- Manifest aggregate SHA-256: `575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460`
- Coverage artifact: `security_ir_artifacts/corpora/xaman-app/source-coverage.json`

The checked-in coverage artifact is manifest-bound but content-unavailable for most ledger/transaction files and does not include the review modal root. This task reviewed the manifest-pinned Xaman source at the exact commit and bound each fact to source path, line range, and SHA-256 evidence.

## Field Model Summary

`BaseTransaction.CommonFields` (`src/common/libs/ledger/transactions/common.ts`) defines the fields shared by every transaction type: required `hash`, `TransactionType`, `Account`, `Sequence`, `LastLedgerSequence`, plus optional `SourceTag`, `Memos`, `Flags`, `Signers`, `Fee`, `TicketSequence`, `NetworkID`, `FirstLedgerSequence`, `OperationLimit`, `SigningPubKey`, `TxnSignature`, `HookParameters`, `AccountTxnID`, `PreviousTxnID`. Concrete transaction classes extend this with their own `Fields`:

- `Payment`: required `Amount`, `Destination`; optional `DestinationTag`, `InvoiceID`, `SendMax`, `DeliverMin`, `Paths`, `CredentialIDs`.
- `TrustSet`: required `LimitAmount`; optional `QualityIn`, `QualityOut`.
- `SignerListSet`: optional `SignerQuorum`, `SignerEntries`.

`Amount`-typed fields normalize to a common shape: native amounts are drops converted to the connected network's native asset; issued-currency amounts keep `currency`, `value`, and an `issuer`. `NetworkID` is only auto-populated for non-legacy networks (network id greater than 1024).

## Modeled Facts

### Account

`AccountID.ts` validates every assigned account value as a real XRPL classic address using `xrpl-accountlib`, rejecting invalid addresses before they are stored. When the user selects a signing account, `ReviewTransactionModal.setSource` writes it into `transaction.Account` unless the payload is multisign or the transaction type is `Import`; `Sign.mixin.ts` independently fills `Account` from the chosen account if it was never set.

### Destination

`Payment.Fields` declares `Destination` as a required `AccountID` field, so every Payment transaction carries a validated recipient address that is distinct from and independently typed alongside `Account`.

### Amount

The `Amount` field codec (`parser/fields/Amount.ts`) branches on the network's native asset: native values are drops converted for display, issued-currency values keep `currency`, `value`, and `issuer`. `PaymentValidation` rejects a missing or zero `Amount.value` unless the transaction already carries `Paths`. `AmountParser` (`parser/common/amount.ts`) validates numeric string input and rejects fractional drop amounts.

### Fee

`Fee` is an optional `Amount`-typed common field. `Sign.mixin.prepare()` throws `global.transactionFeeIsNotSet` if `Fee` is undefined before any further signing preparation happens, guaranteeing a fee is always shown to the user before signing.

### Sequence

`Sequence` is required on `CommonFields` with the `UInt32` type, alongside `LastLedgerSequence` (also required) and optional `TicketSequence`. If `Sequence` is undefined when `prepare()` runs, the client fetches the live account sequence via `LedgerService.getAccountSequence`, which reads `account_data.Sequence` from a fresh account-info response; a fetch failure aborts signing.

### Network

`NetworkID` is an optional `UInt32` common field. `populateFields()` sets it from the connected network only when the network id is greater than 1024 (the legacy-network threshold). Before opening the signing overlay, `sign()` checks `NetworkService.getNetworkDefinitions().transactionNames` and rejects signing if the transaction type is unsupported by the connected network.

### Memo

`Memos` is an optional `STArray` common field using the `Memos` codec. `MemoParser.Encode` detects hex-looking binary blobs with a regex and tags them `application/x-binary`; otherwise it hex-encodes the input as `text/plain`. `MemoParser.Decode` reverses `hex`, `utf8`, `hexasint`, and `int` format encodings for display.

### Issued Currency

The `Amount` setter only stores a value for a non-native currency when an `issuer` is present, and `AmountType` always declares an optional `issuer` alongside `currency` and `value`. `IssueType` pairs a required `currency` and `issuer` and is used as the peer parameter for trust-line lookups via `LedgerService.getFilteredAccountLine`.

### Trustline

`TrustSet.Fields` requires `LimitAmount` (an issued-currency `Amount`) and allows optional `QualityIn`/`QualityOut`, exposing `Currency`/`Issuer`/`Limit` convenience getters. `PaymentValidation` blocks sending an issued currency to a destination that is not the issuer unless the destination already has a trust line with a nonzero limit or balance; it also checks the sender's trust line balance and `freeze_peer` flag (non-issuer sender) or obligation headroom against `limit_peer` (issuer sender) before allowing the payment. `LedgerService.getFilteredAccountLine` resolves a specific trust line by requesting the `ripple_state` ledger entry and only returns a trust line when the relevant reserve flag is set.

### Multisign

`SignerListSet.Fields` declares optional `SignerQuorum` and `SignerEntries` (with the `SignerEntries` codec), modeling the on-ledger multisign quorum structure. `Payload.isMultiSign()` is a boolean coercion of the backend-provided `meta.multisign` flag and is the single source of truth the client uses to branch behavior: `ReviewTransactionModal.setSource` does not overwrite `Account` for multisign payloads, the account-activation live check and client-side validation are both skipped, and `Sign.mixin.sign()` skips `prepare()` (fee/sequence population) when `multiSign` is true. `Payload.shouldSubmit()` is false whenever `isMultiSign()` is true, and `submit()` records the signing account under a `multisigned` patch field instead of auto-dispatching to the ledger. The `submit_multisigned` request/response types document that XRPL only accepts the transaction when the combined weights of the `Signers` array meet or exceed the `SignerList` quorum.

### Transaction Type

`TransactionType` is required on `CommonFields`, and every concrete transaction class sets `this.TransactionType` to its own static `Type` in its constructor. `TransactionFactory.getTransaction` requires `TransactionType` to be present in the input JSON and falls back to a generic `FallbackTransaction` for unregistered types instead of throwing. `ValidationFactory.fromTransaction` resolves a `${item.Type}Validation` export and throws if no matching validation function is found, so every registered transaction type must ship a validation function (even a no-op stub).

## NOT_MODELED Gaps

The artifact marks the following as `NOT_MODELED`:

- `TrustSetValidation` and `SignerListSetValidation` are unimplemented stubs that always resolve, so the reviewed client source provides no additional client-side trust-line or signer-list safety checks beyond field typing for these two transaction types.
- Authoritative XRPL server-side (rippled) enforcement of amount, fee, sequence, reserve, freeze, or rippling rules, and the tec/tem/tef result codes that enforcement produces.
- The external process, device coordination, or storage by which the full set of required multisign signer shares are collected and combined into a `submit_multisigned` request meeting quorum.
- Deployed app binary, backend deployment, node endpoint configuration, and runtime trace equivalence to the reviewed source.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_xrpl_transaction_model.py -q
```

The tests validate required transaction-semantics categories, manifest-bound evidence hashes, required modeled facts, the field model, trustline/issued-currency/multisign constraint details, transaction-type dispatch behavior, explicit `NOT_MODELED` gaps, and documentation references.
