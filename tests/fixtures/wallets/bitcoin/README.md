# Bitcoin wallet fixtures (WALPROC-G400)

Offline golden fixtures for Bitcoin UTXO and script processing. Shared
conformance checks come from `../_shared/` via `WalletProcessorConformance`.

## Coverage

| File | Scenario |
| --- | --- |
| `scripts_legacy_segwit_taproot.json` | Legacy P2PKH/P2SH, SegWit v0, Taproot |
| `coinbase.json` | Coinbase input / subsidy output |
| `multi_input_output.json` | Multi-input multi-output spend + fee |
| `spent_unspent.json` | Create then spend a UTXO |
| `replacement_rbf.json` | Mempool replacement (RBF-style) |
| `network_mismatch.json` | Address/network and genesis binding failures |
| `reorg_utxo.json` | Reorg reverses UTXO effects |
| `sample_transactions.json` | Esplora-shaped sample stream for provider tests |

## Guarantees

- Amounts are integer **satoshis** (no binary floats).
- State is **UTXO-driven**; no account-style debit ledger.
- Ownership/change clustering is **not** asserted.
- Confirmation depth thresholds are **policy**, not universal truth.
- Fixtures are synthetic and offline by default.
