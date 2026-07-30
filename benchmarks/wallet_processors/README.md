# Wallet processor benchmarks

Deterministic offline benchmarks for `ipfs_datasets_py.processors.wallets`
(WALPROC-G640).

## Fixture-only (default / CI)

```bash
python ipfs_datasets_py/benchmarks/wallet_processors/run.py --fixture-only
```

This path:

* Uses a fixed synthetic record set (no network I/O).
* Reports **records/second** and **peak memory**.
* Evaluates a fixture-derived :class:`ResourceBudget` (never live provider
  latency alone).
* Emits a payload-free :class:`IngestRunReceipt` snapshot.

## Live smoke (disabled by default)

Live smoke remains **disabled** unless both are supplied:

* `--approve-endpoint <url>` (repeatable allowlist)
* `--network-approval-id <token>`

Even with approval, this CLI only validates the gate; it does not set
performance budgets from live latency.

## Budget policy

Do **not** set performance budgets from live provider latency alone. Use the
fixture report and operator policy documented in
`docs/operations/WALLET_PROCESSOR_RUNBOOK.md`.
