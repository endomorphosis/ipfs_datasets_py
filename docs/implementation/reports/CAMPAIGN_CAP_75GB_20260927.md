# Campaign storage cap: 75 GB

The user authorized increasing the campaign storage cap from **62,000,000,000
to 75,000,000,000 bytes** on September 27, 2026. The canonical resource
controller and live reservation ledger now use that cap. The **50 GB
per-worker limit remains unchanged**.

The migration held the existing ledger lock, verified the expected original
SHA-256, retained a byte-exact backup, and atomically replaced the ledger. Only
the top-level limit changed: all **88 existing records** were preserved,
including **36 retained** and **52 released** records. Historical per-record
limits, failed claims, child history, and accounting values remain intact.
The canonical controller successfully read the migrated ledger without
acquiring a reservation or host resource lease.

| Evidence | Value |
| --- | --- |
| Previous ledger SHA-256 | `3ea8907c2e2e06fa5e0da4e4bfa4118902408178e4bfd877d8dfebc3301d9c12` |
| Migrated ledger SHA-256 | `ef60f23dcbcee5d58e7fd6d12e817e15e781a47efb2b3298e7e905a9052e4df2` |
| Ledger bytes | 172,781 |
| Resource tests | 56 passed |
| Pure migration tests | 6 passed |

The resource tests include rejection of unmigrated 50, 60, and 62 GB ledgers
and preservation of their historical accounting after an explicit migration.
An initial pytest invocation stopped before collection because the repository
configuration requires pytest's cache provider. Its diagnostic is retained;
the subsequent run used a private cache directory and passed all 56 cases.

The private smoke wrapper now expects 75 GB; its prior version is retained.
**The retry has not been executed as part of this change.** This report records
resource configuration and tests only; it supplies no training, performance,
formalization, or Lean-admission evidence. Existing 62 GB and proposed 62.2 GB
evidence remains unchanged.

The [evidence manifest](evidence/campaign-cap-75gb-20260927/manifest.json)
binds every published artifact and identifies the private authority receipt.
The [applied migration receipt](evidence/campaign-cap-75gb-20260927/application-receipt.json)
records the completed ledger change. `source-application.json` records the
earlier source-edit phase, before the ledger migration. Full ledger backups
remain private at:

`/home/barberb/lift_coding/.git/modules/external/ipfs_datasets/concurrent-autoformal-smoke-20260927/cap-75gb/applied-migration/`
