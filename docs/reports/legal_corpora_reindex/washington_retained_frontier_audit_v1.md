# Washington retained-frontier audit v1

Audit date: 2026-08-26

Scope: read-only reconciliation of every retained Washington dataset,
prospective acquisition ledger, partial checkpoint, and shared cache entry
found under `/home/barberb/.ipfs_datasets`. The audit used the current strict
RCW hierarchy and section parsers with both scraper caches disabled. It made
no network request and did not alter retained evidence or acquisition output.

## Exact source hierarchy

The exact official parser-input hierarchy is:

```text
54,923 = 1 root + 101 title catalogs + 2,785 chapter catalogs
       + 52,036 section-detail leaves
```

All identities are unique and preserve official source order. Their canonical
URL-list SHA-256 digests are:

- titles: `8cbd68bd62ed53489258078080d44a838213d69ff02d63e8436e4f90e80b0c9f`;
- chapters: `be47d2103a3b291ddb578e85fc96cf67fc0cc9a7aec1c4f46fab8cbf17ba8ec6`;
- section leaves: `47920c315a01033785b2dbf31750ed73d3374ff6cf0b1bfc1fbb0d11cbc82163`.

Ten chapter catalogs have no section-detail rows. The retained catalog bytes
type two of them as admitted redistricting-plan records (`29A.76C` and
`44.07F`) and eight as source-bound chapter terminals: four cross-references,
two notes-only cross-references, one reserved chapter, and one recodified
chapter. The fixity-bound ten-chapter projection has SHA-256
`925691d864da183bf8c3dd381ed9597991be8e28ac36f0b61edaa7b7a004eba5`.

Consequently, the complete source-outcome algebra will cover 52,046 units:

```text
52,046 = 52,036 section leaves + 2 chapter-material records
       + 8 typed chapter terminals
```

## Retained evidence and residual

The only prospective Washington ledger is
`full-acquisition-evidence-v15-wa-v1/WA`. It contains 4,423 unique fetch
receipts and 4,423 unique content objects:

```text
4,423 = 1 root + 101 titles + 2,785 chapters + 1,536 sections
```

All 518,917,470 retained bytes rehash to their receipt, parser-envelope, and
transport digests. Every request is an exact sanitized GET to a unique
official URL, every transport is direct, and every row authorizes parser
admission. The sorted evidence projection SHA-256 is
`c1f5a13118797a0ae91b21c269f94548013f9822cd6027f8a1864fb588ec66a4`.

The current parser classifies all 1,536 retained section pages as operative,
with zero section terminals and zero unclassified pages. Their normalized
projection SHA-256 is
`f55facd3fc1d9a078bcb2cb3ac49788e2105bb45a9c057b4d3c07002b430c2a6`.
No chapter-catalog heading matches the strict section-terminal vocabulary, so
none of the remaining pages can be skipped by inferring a lifecycle status
from its heading.

The exact section residual is therefore the source-ordered difference between
the 52,036 section leaves and 1,536 retained section URLs:

```text
52,036 = 1,536 known operative + 0 known terminal + 50,500 unresolved
```

Its canonical URL-list SHA-256 is
`e41a7baf281a3d6aea92693f7263020f441f86e5f0da7efb596726b2f14a0489`.
The first residual is
`https://app.leg.wa.gov/RCW/default.aspx?cite=7.05.230`; the last is
`https://app.leg.wa.gov/RCW/default.aspx?cite=91.08.900`. The residual's
operative/terminal split must remain unresolved until those exact responses
are retained and parsed.

## Nonduplication audit

The complete `state_laws` tree contains exactly 4,423 Washington prospective
fetch receipts, all in the v15 ledger above. No second evidence root contains
a reusable Washington parser input.

The shared legal-page cache has 112,890 entries at index SHA-256
`95f67deb87402adc0f477f70d460c94d07879a05b6493efef516d752894eb5ad`.
Only two entries point to RCW URLs (`1.20.051` and `1.20.055`); both URLs are
already in the prospective ledger, neither belongs to the residual, and both
cache bodies have older, conflicting digests. They cannot replace the retained
current bytes. The default legal fetch-cache directory contains no reusable
Washington object.

The old `catalog-first/WA` snapshot is a 101-row, `bundle_closed=false` root
observation with no `receipt.json`; its root bytes differ from the prospective
ledger. The legacy local Washington JSON-LD/Parquet pair contains only the
normalized RCW `9A.32.030` seed and no parser-input receipt. That normalized
row is not authorizing evidence and cannot remove its URL from the residual.
The ten `staging-wa-v1` through `staging-wa-v10` outputs are preserved
incomplete diagnostics; none produced a Washington JSON-LD or Parquet shard,
and their usable parser inputs are already represented once in v15.

## Batched acquisition contract

The strict Washington path now submits the complete 52,036-leaf union once to
the shared plural transport. The ledger replays the 1,536 retained section
inputs first, so only the exact 50,500-URL difference is eligible for network
work. The initial residual wave explicitly enables one Wayback prefix
inventory and one Common Crawl domain/path inventory, groups and coalesces
ranges by immutable WARC object, and disables legacy per-page archive
discovery. Bounded retries contain only unresolved URLs and do not repeat
grouped archive discovery. The 256-row parse/checkpoint slice remains bounded
but no longer fragments transport into separate archive request waves.

Root, title, and chapter discovery remain three dependency-ordered plural
waves because each level supplies the next level's exact identities. Within
each discovered level, same-domain pages and same-WARC ranges are bundled.

The current producer identity, which now binds the base plural transport,
archive client, strict closure code, Washington parser, and Wayback engine, is
`ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington.WashingtonScraper@sha256:3baf89518dcf6b9736c2457773bf8c2899c8a3b6feaabd52e7a0d5eb7b8f22cf`.
Current source SHA-256 values are
`31dee559d45acca170f7256802ac22796b483f9dcf3235387b283f516e16ff7a`
for `washington.py` and
`c423dfcd45ab87cdab4149df8d6a72db7e7391d559af507f7f2065bbfbe06612`
for `washington_section.py`.

## Exact next commands

Both proposed output paths are currently absent. The live residual run is:

```bash
env LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED=0 \
  LEGAL_SCRAPER_FETCH_CACHE_ENABLED=0 \
  STATE_SCRAPER_WA_FRONTIER_CONCURRENCY=16 \
  STATE_SCRAPER_WA_SECTION_BATCH_SIZE=256 \
  STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS=1 \
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states WA \
  --output-root /home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260824/staging-wa-v11 \
  --scrape \
  --acquisition-evidence-root /home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260824/full-acquisition-evidence-v15-wa-v1 \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-load-completed-states-baseline \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --parallel-workers 1 \
  --per-state-retry-attempts 1 \
  --per-state-timeout-seconds 28800 \
  --timeout-recovery-rounds 0 \
  --progress-heartbeat-seconds 30 \
  --json
```

After, and only after, v11 closes and retains all 54,923 inputs, run the same
command with `--retained-replay-only` and output root `staging-wa-v12`. Require
zero network requests, exact first/replay frontier equality, zero unresolved
dispositions, canonical JSON-LD/Parquet parity, and a publication-authorizing
normalized receipt before adding Washington to the exact-51 candidate set.

## Validation

With both caches disabled, 69 focused Washington/plural-lifecycle tests pass
and three retained-evidence tests skip because their optional evidence roots
are not configured. The 19-test cohort-L run has all Washington checks green;
its two failures are pre-existing Vermont report-count and Virginia live-title
count drift, not Washington failures.
