# New Hampshire retained-source and exact-current blocker audit v1

Date: 2026-08-26  
Scope: official RSA hierarchy metadata only; no chapter body, section body,
normalization, indexing, or publication wave was run.

## Readiness decision

New Hampshire is **not ready to materialize or publish**.  The retained
hierarchy is internally exact, but it is historical: the root is a January
2025 Wayback capture and the 11 retained title pages are February 2025 Wayback
captures.  Their August 2026 `retrieved_at` values describe replay time, not
the date of the law.  They therefore cannot authorize an exact-current 2026
corpus or a 2026 `legal_as_of` claim.

Relative to that historical root, a bounded plural title-catalog wave closed
11 of 66 active title pages before archive replay transport failed.  Those 11
pages expose 603 chapter-catalog locators.  The other 55 title pages, all
chapter-catalog contents, the section frontier, and therefore the body
residual remain open for that snapshot.  The 55-page residual must not be
carried forward as the current residual until a fresh official root observation
recomputes title membership, order, and terminal dispositions.  No missing
count is inferred from an older artifact or from static URL construction.

## Authorizing retained historical root

The strict v4 ledger retains exactly one root request from before this audit:

- Official request identity:
  `https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm`
- Wayback capture: `20250124114611`
- Bytes: 16,237
- Body SHA-256:
  `5acb11bb3ab6aa7bae620f00d3c022ac08aabb0b3548a1bfe8d177a1d1165611`
- Receipt SHA-256:
  `b579168a413c47791004e9a8c6d47171c1a00acecc6e7de12f50ca6a0aa75e6a`
- The retained envelope, receipt, request URL, object digest, and receipt
  filename all reverify, and `authorizes_parser_admission` is true.

Parsing those exact bytes with `nhtoc_title_units`, while resolving relative
descendants to the configured `gc.nh.gov` host, gives this closed historical
root algebra:

```text
67 discovered titles = 66 active title pages + 1 source-typed terminal title
duplicates by title identity = 0
duplicates by canonical URL = 0
terminal = Title IV, Elections, repealed
terminal source label = (Entire Title Was Repealed - Chapters 54 - 70)
```

The exact canonical-JSON projections are:

- Full 67-unit parser projection SHA-256:
  `858f0855aa05bc075543c1998f2cd675fb54e6468f56d2d506799675601b9a05`
- Ordered 67-title identity SHA-256:
  `19e5b2fea019003ddaaae3875119551dd2a5c605ec59c995d710edb8600ff314`
- Ordered 67 current-host title URL SHA-256:
  `70c26920e96975e4ebb8887bc0106eaf39fe6569c37d2eda3917508cffb68779`
- Ordered 66-active-title identity SHA-256:
  `f62bc93de1d435445105cebe3f9aca96fd41b6629366a6445a0ad26da0d5dc7c`
- Ordered 66-active-title URL SHA-256:
  `40fa7ac3a35dfab87ddf0dd066106d36544dda664567b57671ab2d37bdcd9a6e`

The root also proves the three non-integer title identities `XIX-A`,
`XXXIII-A`, and `XXXIV-A`; they are active and must not be dropped.

It does **not** prove that this projection is current.  No strict parser input
retains `https://gc.nh.gov/rsa/html/NHTOC.htm`, nor is there a retained current
redirect or delegation response that authorizes rewriting the legacy root's
relative links to that host.  The rewrite is deterministic parser behavior,
not source evidence of a current root.

## Bounded historical title-catalog wave

One metadata-only wave requested the exact 66 active current-host title URLs.
It used the shared plural path with direct-first retrieval, one logical Common
Crawl inventory, plural Wayback prefix inventory, grouped/coalesced WARC range
support, and one residual-only retry.  It did not invoke a per-page archive
fallback loop.

Observed transport result:

```text
requested title pages                         66
direct successes                              0
Wayback exact matches                         66
Wayback capture replays succeeded             11
Wayback capture replays failed                55
Common Crawl logical inventories              1
Common Crawl records / WARC ranges            0 / 0
residual-only retry input                      55
residual-only retry recoveries                 0
per-page archive fallback                      disabled
chapter catalog / section / body requests      0 / 0 / 0
```

The plural Wayback inventory used one same-origin prefix group.  Its exact
filters were internally split into nine bounded query-byte chunks; that is
still a plural prefix inventory, not 66 independent archive lookups.  The 11
successes were eagerly retained before the unresolved frontier caused the
metadata probe to stop.  The blocker was archive replay connection refusal,
not a parser guess or an empty-title classification.

The strict v4 ledger now has 12 authorizing **historical** parser inputs: the
root plus these 11 title catalogs.  Every receipt and object reverifies.  The canonical JSON
projection of ordered `{official_url, content_sha256, archive_timestamp,
source_transport}` records has SHA-256
`d675632a7940e0a141618376aeeba516538582af674371c83232235ea4d0bbaa`;
the 12 objects total 122,638 bytes.

| Title | Wayback capture | Bytes | Chapters exposed | Body SHA-256 |
|---|---:|---:|---:|---|
| I | `20250212203224` | 20,580 | 134 | `a22245dd9af5b80cfc5d54257bfa1988828ba55388adf985f92705a00e40486b` |
| II | `20250213040729` | 3,918 | 14 | `eee9cadd4c64ca2de0ae741e5f05fa7488b3c25891a6ec32c4894e37eb318840` |
| III | `20250211150952` | 8,854 | 51 | `e20e5e7006b4024057d3dd6f3d33c68ca0cf1f95fe5f7df930c076a9af21eb2d` |
| V | `20250207155310` | 9,829 | 58 | `769030ec32b07200e28c1f1f2e796e2dc77ee8ffd29c4a4e0772e9f3cbb05337` |
| VI | `20250213022224` | 7,271 | 36 | `9600b2e3cc4bd787f126294c2b860bddf5132fe80d4043f79ba4f7f9d2b4c83d` |
| VII | `20250212190500` | 5,099 | 22 | `70a4af52d870602a34f6094c8b485cddf94885399a1f6fc3b1b5cf17b6e9eb93` |
| VIII | `20250211133318` | 6,178 | 28 | `935dba5d63d5457a5608d33559ceff419e9e376296c18df9e6c88e9a4c4aacec` |
| X | `20250211183041` | 21,447 | 139 | `c8405443bac53376b1926bcc39abf4d2d5d88337e5abe884697877dc59732a82` |
| XII | `20250211200438` | 17,414 | 109 | `96861e68f6021b241a35c33f3a32bdef3022af2db90a964cadafc5e07c156279` |
| XIII | `20250211173012` | 3,034 | 7 | `8d8df226fb6f4a0d1c6f450ac3c45ac375b3cf6c628b30f2ec2f289dedafcca2` |
| XIV | `20250211134346` | 2,777 | 5 | `59c15011b491ad3ad3a34567a260953bfcfa8998229bcefdb57e7b4d3f8b4651` |

Each page passed the title-payload validator and its requested `<h2>` identity.
Across their source-derived chapter members:

```text
603 discovered chapter locators = 603 active + 0 terminal
duplicate (title, chapter) identities = 0
duplicate canonical URLs = 0
```

- Canonical JSON SHA-256 of the ordered 603 complete
  `nhtoc_chapter_units` dictionaries:
  `429021d228d941f8e824708f9b9c38c892f65dd7a2354de183c2dae4ac96b329`
- Ordered active chapter URL SHA-256:
  `9caf13af6dc5f606acaae7e6292a1f6507f62e96aead79ddd9ab7a7b04ec1e3e`

These are chapter **catalog locators**, not section counts and not statutory
body rows.  None of the 603 chapter catalog documents was opened in this
audit.

## Historical residual and the point where exactness stops

The retained title identity projection is
`845b98ae0af566ca288bad1fcc124d65d2fd5e4d285be5501a677c4711cd81c2`.
The ordered 55-title residual identity projection is
`d0e4804123026a8a35d0f3b0a8b9139c4dae3805cd48858c4869be03a65176a1`
and its URL projection is
`a878ed452266146b100b5fc0b7fca28a583cbb7f6a19051e762568028a42fe85`.

Residual titles, in retained 2025 root order:

```text
IX, XI, XV, XVI, XVII, XVIII, XIX, XIX-A, XX, XXI, XXII, XXIII, XXIV,
XXV, XXVI, XXVII, XXVIII, XXIX, XXX, XXXI, XXXII, XXXIII, XXXIII-A,
XXXIV, XXXIV-A, XXXV, XXXVI, XXXVII, XXXVIII, XXXIX, XL, XLI, XLII,
XLIII, XLIV, XLV, XLVI, XLVII, XLVIII, XLIX, L, LI, LII, LIII, LIV, LV,
LVI, LVII, LVIII, LIX, LX, LXI, LXII, LXIII, LXIV
```

The currently provable **historical** hierarchy-input lower bound is:

```text
strict reusable inputs                         12 = 1 root + 11 titles
known metadata residual floor                 658 = 55 titles + 603 chapters
known total metadata-input floor              670
additional chapter catalogs from 55 titles    unknown
section catalog members and terminals          unknown
exact active section/body residual             unknown
```

Consequently, no complete chapter, section, operative-body, terminal-body, or
publication algebra can yet be asserted.  The 658/670 figures are bounds for
the retained 2025 projection, not current-source bounds.  A count from the old
caches would likewise be a historical diagnostic, not current strict closure.

## Prior-work reuse audit

No earlier dataset was silently reacquired or promoted:

- `catalog-first/NH` claims a closed 64-row catalog, but its body is a static
  locator projection (SHA-256
  `c1cd8d175416cfeef009ee688f2849229400db2c6d7dd6e4ca0f02f29431c270`),
  omits all three `-A` titles, uses stale labels, and has no `receipt.json`
  despite naming one in its checkpoint.  It is nonauthorizing and contains no
  statutory bodies.
- Four May fetch caches contain 1,251 NH records representing 650 unique
  archive replay URLs: 67 title catalogs, 113 chapter catalogs, 468 section
  pages, one root, and one other URL.  All 650 local `.bin` objects match their
  cache SHA, but none of the records has an aligned origin transport receipt.
  The same nominal archive title URL can have multiple distinct hashes.  Only
  129 of 176 stored title-page observations pass both the strict payload and
  requested-title identity checks, spanning 53 titles.  They remain useful
  diagnostics but cannot enter the strict ledger.
- The shared page-cache index has 634 NH entries.  Eleven are the newly
  retained current-host title receipts.  The other 623 are old-host entries
  (one root, one Title I page, 29 chapter catalogs, 28 merged pages, and 564
  section pages).  Even where the index carries direct transport metadata,
  `www.gencourt.state.nh.us` and `gc.nh.gov` are distinct request identities;
  the strict adapter intentionally does not relabel an old-host descendant as
  its current-host counterpart.
- Older partial checkpoints retain 120, 497, or 1,041 normalized rows, but
  they have no embedded acquisition receipts and mix archive captures and
  source hosts.  The 1,041-row checkpoint's identity projection is
  `6d666e0561537e3b542fc69057b5f4350bf9625e13b28790f743aa3091ee38dd`.
  Its `complete` label is not source-frontier closure.
- The currently installed `STATE-NH` JSON-LD/Parquet pair has 112 rows.  They
  are chapter-locator prose stubs over Titles I-VIII, not section bodies, and
  therefore are not a reusable current statutory corpus.

This classification preserves all prior artifacts without granting them
authority they do not contain.

## Batching and replay invariants

The NH strict adapter keeps each same-domain hierarchy or body wave on the
shared plural acquisition seam:

- direct requests are plural and concurrency-bounded;
- each frontier batch requests at most one logical Common Crawl inventory;
- WARC pointers are grouped and byte ranges coalesced before download;
- Wayback uses plural prefix inventory;
- retries contain only unresolved URLs and do not repeat archive inventory;
- no per-page archive loop is enabled; and
- final closure reparses exact ledger objects with zero network requests.

The 66-title root wave fits under the default 512-page NH frontier batch size,
so it is one logical inventory wave.  Later chapter and section waves remain
bounded at 512 pages each; they never become one archive lookup per page.

The production adapter now passes
`repeat_grouped_archive_inventory_on_residual=False` explicitly instead of
depending on the shared helper's default.  The focused NH end-to-end tree
regression proves that root, title, two-chapter, and two-section waves each use
the plural seam with Wayback prefix inventory and the explicit no-repeat
policy.  Shared transport regressions independently prove one Common Crawl
inventory with same-WARC range coalescing, direct-only residual retries after
grouped inventory, and a 33-page same-origin Wayback wave with no per-page
archive fallback.  Source order is preserved by aligned URL/result vectors,
the breadth-first parent loops, and final input/operative identity projections;
no source-order production gap was found.

## Safe continuation

Do **not** resume the 55-title wave against the v4 ledger as an exact-current
operation.  Exact retained replay wins before network acquisition, so the
legacy root and 11 title identities would remain pinned to their 2025 bodies.
Appending changed bodies for the same GET identities would also make retained
replay ambiguous rather than refreshing those identities.  Keep v4 immutable
as a historical diagnostic.

There is not yet a checked-in metadata-only acquisition command, and the full
refresh command is not a safe substitute because it proceeds into chapter and
section bodies as soon as metadata closes.  The next acquisition must therefore
be a bounded metadata probe with this exact plan:

1. Allocate a fresh evidence root, for example
   `full-acquisition-evidence-v5-nh-current-v1/NH`; do not seed it from v4.
2. Request and retain `https://gc.nh.gov/rsa/html/NHTOC.htm` first.  If the live
   official response delegates to the legacy host, retain the redirect or
   delegation evidence rather than inferring equivalence between hosts.
3. Validate the root payload and recompute the ordered title identity, URL,
   active, and source-typed terminal projections.  Stop on any duplicate,
   identity mismatch, or unbound host rewrite.
4. Submit that newly derived active title frontier as one same-domain plural
   metadata wave.  Validate every requested title against its returned `<h2>`
   identity and stop on any residual.  Recompute the residual from this fresh
   root; do not assume it is 55.
5. Only after fresh title closure, derive chapter URLs in source order and
   continue bounded plural metadata waves, then section locators and bodies.

Before that probe can authorize publication, production also needs an explicit
source-observation contract at `_scrape_official_rsa_tree_batched`: it currently
sets `legal_as_of` from `datetime.now()` after traversal.  That can mislabel old
Wayback bytes as current.  Retained inputs must instead supply a coherent
source/capture date or fail closed; no cutoff or mixed-snapshot policy is
encoded here because the retained evidence does not authorize one.

Do not launch normalization, embedding, BM25, graph, centroid/meta-index, or
publication stages until the fresh title and chapter catalogs close, exact
active/terminal section algebra is known, every active section body is
retained, freshness admission is source-bound, and ledger-only replay
reproduces the same frontier and normalized identities.

## Narrow hardening in this audit

`NewHampshireScraper` declares the exact 66-active/one-terminal historical
title projection and fails closed if the retained root loses or broadens Title
IV's source-typed `repealed` status.  Focused regressions also pin the three
labels that were stale in the old 64-row catalog and now bind the no-repeat
archive-inventory policy explicitly.  No acquisition artifact was deleted or
rewritten.  The resulting strict source-software identity is
`ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire.NewHampshireScraper@sha256:5ff723c9aa7886d99a548a3a10e39a0eb9d3c863b589f2333a3e7d677eb02250`.
