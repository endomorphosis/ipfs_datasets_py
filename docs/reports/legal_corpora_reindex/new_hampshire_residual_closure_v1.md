# New Hampshire residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-096`  
Goal: `LCR-G152`  
Track: `exact51-residual-wave-c`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-096 by recording the exact remaining New Hampshire
residual: start from a fresh current official root at
`https://gc.nh.gov/rsa/html/NHTOC.htm`, then derive title, chapter, and
section membership only from that observation. Host zero-network replay
has not sealed a current-bundle pair. The six closed-state steps remain
the only admitted path. Hub mutation, a static residual list, a per-page
archive loop, resuming the v4 2025 Wayback root as exact-current, carrying
forward the historical 55-title residual, and deriving `legal_as_of` from
wall-clock on 2025 bytes are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | NH |
| official domain | gc.nh.gov |
| official entry | `https://gc.nh.gov/rsa/html/NHTOC.htm` |
| legacy_entry | `https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm` |
| current_official_entry | `https://gc.nh.gov/rsa/html/NHTOC.htm` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | official RSA NHTOC title/chapter/section HTML tree |
| seed | zero authorizing current-ledger inputs; start at the current official root |
| resume_v4_2025_wayback_root | forbidden |
| resume_staging_nh_v4 | forbidden |
| seed_from_v4 | forbidden |
| carry_forward_historical_title_residual | forbidden |
| equate_legacy_and_current_hosts_without_delegation_proof | forbidden |
| legal_as_of_wall_clock_on_2025_bytes | forbidden |
| static_residual_list | forbidden |
| invent_later_title_targets | forbidden |
| per_page_archive_loop | false |
| retained_current_root_inputs | 0 |
| historical_v4_parser_inputs | 12 |
| historical_v4_root_plus_titles | 1 root + 11 titles |
| historical_v4_root_wayback_capture | 20250124114611 |
| historical_v4_root_bytes | 16237 |
| historical_v4_root_body_sha256 | `5acb11bb3ab6aa7bae620f00d3c022ac08aabb0b3548a1bfe8d177a1d1165611` |
| historical_v4_root_receipt_sha256 | `b579168a413c47791004e9a8c6d47171c1a00acecc6e7de12f50ca6a0aa75e6a` |
| historical_v4_titles_discovered | 67 |
| historical_v4_active_titles | 66 |
| historical_v4_terminal_titles | 1 |
| historical_v4_terminal_title | IV repealed |
| historical_v4_title_residual | 55 |
| historical_v4_chapters_from_11_titles | 603 |
| title_membership_count | source_dependent_after_current_root |
| chapter_membership_count | source_dependent_after_current_root |
| section_membership_count | source_dependent_after_current_root |
| residual_count | 1 |
| residual_kind | fresh current official root then source-derived title/chapter/section membership |
| residual_first_url | `https://gc.nh.gov/rsa/html/NHTOC.htm` |
| residual_wave_name | `root` |
| title_wave_name | `titles` |
| chapter_wave_name | `chapters` |
| section_wave_name_prefix | `sections-` |
| root_acquisition_wave_count | 1 |
| title_acquisition_wave_count | 1 |
| fetch_current_root_before_titles | true |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_ordered_sha256_prefix | fresh_current_root_gc_nh_gov |
| diagnostic_producer | `NewHampshireScraper@sha256:5ff723c9aa7886d99a548a3a10e39a0eb9d3c863b589f2333a3e7d677eb02250` |

The residual SHA-256 prefix `fresh_current_root_gc_nh_gov` names the
one-URL current-root array
`["https://gc.nh.gov/rsa/html/NHTOC.htm"]`. Recompute that digest only
from that exact current-host GET identity. This report does not emit a
66-title or 55-title URL dump: a static dump would be a forbidden
residual list and would exceed the compact-recipe admission bound.
Title, chapter, and section counts remain source-dependent on the fresh
current root and are therefore not predeclared integers.

## Outcome

New Hampshire is **not** assembler-eligible. No retained current-host
root exists. The strict v4 ledger retains a January 2025 Wayback capture
of the legacy `www.gencourt.state.nh.us` root plus eleven February 2025
Wayback title pages. Those bytes cannot authorize an exact-current 2026
corpus or a 2026 `legal_as_of` claim. No host retained-replay seal,
normalized receipt, JSON-LD/Parquet pair, or current-bundle pair exists
for a current-root observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is to allocate a fresh absent
evidence root, request and retain
`https://gc.nh.gov/rsa/html/NHTOC.htm` first, recompute title membership
from that payload, submit the newly derived active title frontier as one
same-domain plural wave, then continue source-ordered chapter and
section waves, and finally host `--retained-replay-only` with zero
network before materialization.

## Fresh current root, not the v4 Wayback bootstrap

The official live RSA tree now lives at `gc.nh.gov`. The adapter still
names a distinct legacy request identity at
`https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm` and rewrites
relative descendants onto `gc.nh.gov`. That rewrite is deterministic
parser behavior. It is **not** source evidence that a current root was
observed. No strict parser input retains
`https://gc.nh.gov/rsa/html/NHTOC.htm`, and no retained current redirect
or delegation response authorizes equating the two hosts.

The v4 authorizing historical root is:

```text
legacy GET  https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm
Wayback     20250124114611
bytes       16,237
```

Parsing those exact historical bytes produced 67 titles (66 active plus
Title IV, Elections, as a source-typed `repealed` terminal). A bounded
plural title wave then closed 11 of those 66 active title pages before
archive replay transport failed, exposing 603 chapter-catalog locators
and leaving a 55-title historical residual. That 55-title remainder,
the 12 v4 parser inputs, and the 603 chapter locators are **historical
diagnostics**. They must not be carried forward as the current residual.
A fresh official root may add, drop, reorder, or reclassify titles,
including the three non-integer identities `XIX-A`, `XXXIII-A`, and
`XXXIV-A`. Recompute membership from the current-root payload. Do not
assume the residual is 55.

Required current-root algebra after the fresh GET succeeds:

```text
1 current-root GET
  → N titles = A active title pages + T source-typed terminal titles
  → chapter catalogs derived only from those A title pages
  → section locators and bodies derived only from those chapter catalogs
```

`N`, `A`, `T`, chapter counts, and section counts are unknown until the
current root is retained. Guessing them from v4, from `OFFICIAL_TITLES`,
or from the catalog-first 64-row static locator projection fails closed.

## Exact remaining URL

The exact next URL is the current official root:

```text
https://gc.nh.gov/rsa/html/NHTOC.htm
```

That locator is the live General Court RSA table of contents. It is not
the legacy `www.gencourt.state.nh.us` GET, not Wayback
`20250124114611`, not `NHTOC-IX.htm` as the first historical 55-title
remainder, and not an invented later `NHTOC-XCIX.htm` path.

If the live official response delegates or redirects to the legacy host,
retain the redirect or delegation evidence rather than inferring host
equivalence. Do not relabel a `www.gencourt.state.nh.us` descendant as
its `gc.nh.gov` counterpart without that proof. The two request
identities remain distinct until a current observation says otherwise.

The exact remaining proof residual is:

1. The one-URL current-root wave at SHA prefix
   `fresh_current_root_gc_nh_gov`.
2. Source-bound `legal_as_of` for whatever bytes that GET actually
   returns. The adapter currently stamps `legal_as_of` from
   `datetime.now()` after traversal. That wall-clock stamp must not
   label 2025 Wayback bytes as current. Retained inputs must supply a
   coherent source or capture date, or fail closed.

Recompute any later residual SHA only from source-ordered URLs derived
after the current root closes, using
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## One current-root wave, then source-derived descendants

The adapter already reconstructs the official tree as ordered plural
waves: `root`, `titles`, `chapters`, then `sections-*`. After a fresh
absent evidence root, the unresolved first remainder is exactly the
current-host `NHTOC.htm` GET. Titles must close from that payload
before any chapter or section union is submitted. Residual retries do
not repeat grouped archive inventory. Do not invent a second per-title,
per-chapter, per-page, or CDX loop.

Required acquisition shape:

1. Allocate a fresh evidence root, for example
   `full-acquisition-evidence-v5-nh-current-v1/NH`. Do not seed it from
   v4. Destination jurisdiction directories must be absent
   (`copied_file_count=0`). Keep v4 immutable as a historical
   diagnostic.
2. Request and retain `https://gc.nh.gov/rsa/html/NHTOC.htm` first as
   one plural `root` wave (`--allowed-source-transport direct`). Prefer
   direct. If the response delegates to the legacy host, retain that
   proof; do not infer equivalence.
3. Validate the root payload (`New Hampshire Statutes`, table of
   contents, `NHTOC/NHTOC-` locators). Recompute ordered title identity,
   URL, active, and source-typed terminal projections. Stop on any
   duplicate, identity mismatch, or unbound host rewrite.
4. Submit the newly derived active title frontier as one same-domain
   plural `titles` wave. The default 512-page NH frontier batch keeps a
   66-title historical catalog in one logical inventory; a freshly
   derived catalog of similar size remains one wave. Validate every
   requested title against its returned `<h2>` identity. Recompute any
   title residual from this fresh root; do not assume it is 55.
5. Only after fresh title closure, derive chapter URLs in source order
   and continue bounded plural `chapters` waves, then section locators
   and bodies as `sections-*` waves. Do not open one HTTP client or
   archive inventory per page.
6. Use one `gc.nh.gov` (and, only if a retained delegation proof
   admits it, `www.gencourt.state.nh.us`) Common Crawl inventory with
   URL term `/rsa/html/`, grouped/coalesced WARC reuse, and Wayback
   prefix inventory. Residual-only retries must not repeat grouped
   archive inventory.
7. Host-replay every parser input with `--retained-replay-only` and
   zero network. Require first/replay frontier equality, a source-bound
   `legal_as_of` (never wall-clock on 2025 bytes), and
   `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later
  `NHTOC-{ROMAN}.htm` targets;
- carrying the historical 55-title residual, the 12 v4 inputs, or the
  603 chapter locators forward as current membership;
- resuming v4 2025 Wayback roots (`20250124114611`) or `staging-nh-v4` as exact-current;
- deriving `legal_as_of` from wall-clock on 2025 bytes;
- per-page archive loops, per-title CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- seeding or overwriting a destination that already exists;
- stamping historical archive bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity;
- admitting the catalog-first 64-row static locator projection, the
  receiptless May fetch cache, or the 112-row chapter-locator JSON-LD
  stubs as authorizing current evidence;
- submitting titles, chapters, or sections before the current root
  closes.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | New Hampshire binding |
|---|---|
| Source-derived frontier | Fresh `gc.nh.gov` `NHTOC.htm`, then titles, chapters, sections |
| Fresh evidence generation | Absent destination; never seed or resume v4 |
| Direct-only reuse | `--allowed-source-transport direct` |
| Current-root residual | `root`, 1 URL, SHA prefix `fresh_current_root_gc_nh_gov` |
| Title/chapter/section remainder | source-dependent after the current root closes |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual waves close:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states NH \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-nh-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-nh-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is `https://gc.nh.gov/rsa/html/NHTOC.htm`. Inventing a
later `NHTOC-{ROMAN}.htm`, resuming Wayback `20250124114611`, or treating
the first historical 55-title remainder as the current residual fails
closed.

The exact remaining proof residual is that one-URL current-root wave at
SHA prefix `fresh_current_root_gc_nh_gov`, plus source-bound `legal_as_of`
for the bytes actually returned, then the complete source-ordered title,
chapter, and section membership whose counts remain source-dependent on
that root.
