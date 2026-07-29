# XRPL wallet fixtures

Golden offline fixtures for the reusable XRPL ledger processor (WALPROC-G200).

Coverage includes:

- `account_tx` **marker pagination** without gaps or duplicates
- **partial-payment** `delivered_amount` vs requested `Amount`
- **issued currency** identity (currency + issuer)
- **destination tags** and **memos** under privacy policy
- distinct **failed / unvalidated / unknown** outcomes
- **ledger hash/index continuity** anchors for checkpoints

Shared checks come from `../_shared/` via `WalletProcessorConformance`.
Xaman wallet/payload samples remain under `../xaman/`; they must not be
imported into the XRPL ledger provider.
