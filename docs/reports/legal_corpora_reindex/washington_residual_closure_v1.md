# Washington residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-093`  
Goal: `LCR-G151`  
Track: `exact51-residual-wave-b`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-093 by recording the exact remaining Washington
source-ordered RCW section residual after the v15 retained catalogs. Host
zero-network replay has not sealed a current-bundle pair. The six
closed-state steps remain the only admitted path. Hub mutation, a static
residual list, a per-page archive loop, guessed later URLs, and merging
residuals across states are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | WA |
| official domain | app.leg.wa.gov |
| official entry | `https://app.leg.wa.gov/RCW/` |
| official_root | `https://app.leg.wa.gov/RCW/default.aspx` |
| official_section_locator | `https://app.leg.wa.gov/RCW/default.aspx?cite=` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| seed | strict v15 only |
| catalog_first_snapshot | forbidden |
| staging_wa_v1_through_v10 | forbidden |
| shared_cache_residual_reuse | forbidden |
| static_residual_list | forbidden |
| guess_later_urls | forbidden |
| merge_residuals_across_states | forbidden |
| source_hierarchy_inputs | 54923 |
| title_catalog_count | 101 |
| chapter_catalog_count | 2785 |
| source_section_leaves | 52036 |
| source_outcome_units | 52046 |
| chapter_material_records | 2 |
| typed_chapter_terminals | 8 |
| v15_unique_inputs | 4423 |
| v15_root_pages | 1 |
| v15_title_catalogs | 101 |
| v15_chapter_catalogs | 2785 |
| v15_section_pages | 1536 |
| retained_operative_sections | 1536 |
| retained_terminal_sections | 0 |
| residual_count | 50500 |
| residual_kind | source-ordered RCW section URLs |
| residual_first_section | 7.05.230 |
| residual_last_section | 91.08.900 |
| residual_first_url | `https://app.leg.wa.gov/RCW/default.aspx?cite=7.05.230` |
| residual_last_url | `https://app.leg.wa.gov/RCW/default.aspx?cite=91.08.900` |
| residual_ordered_sha256 | `e41a7baf281a3d6aea92693f7263020f441f86e5f0da7efb596726b2f14a0489` |
| residual_ordered_sha256_prefix | `e41a7baf281a` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_wave_name | `section-frontier` |
| hierarchy_wave_count | 3 |
| leaf_acquisition_wave_count | 1 |
| source_ordered_cross_parent_union | true |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| source_bundle_prefix | `ae7af2834278` |
| diagnostic_producer | `WashingtonScraper@sha256:ae7af28342782002a11fd933df2dea5809bb964e3b826ca34b1de1d95255873e` |
| diagnostic_hashes_authorizing | false |

The residual SHA-256 prefix `e41a7baf281a` is the already published identity
of the source-ordered unique RCW section-URL difference. The adapter records
the complete 52,036-leaf union as one `section-frontier` wave; the attached
ledger replays the 1,536 retained section inputs first, so only this exact
50,500-URL difference is eligible for network work. This report does not
emit the 50,500 URLs: a static dump would be a forbidden residual list and
would exceed the compact-recipe admission bound.

## Outcome

Washington is **not** assembler-eligible. Hierarchy membership is known,
v15 retained inputs are known, and the remaining leaf wave is an exact
50,500-URL source-ordered section residual. No host retained-replay seal,
normalized receipt, JSON-LD/Parquet pair, or current-bundle pair exists
for this observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one global leaf wave against a
fresh v15-seeded evidence root, then host `--retained-replay-only` with
zero network before materialization.

## v15 seed algebra

Strict lifecycle derives 101 titles and 2,785 chapters from the official
RCW root, not from a static residual URL list, a sample cap, or guessed
later cites. Ten chapter catalogs have no section-detail rows. The
retained catalog bytes type two of them as admitted redistricting-plan
records (`29A.76C` and `44.07F`) and eight as source-bound chapter
terminals. Consequently the complete source-outcome algebra covers
52,046 units:

```text
54,923 = 1 root + 101 title catalogs + 2,785 chapter catalogs
       + 52,036 section-detail leaves

52,046 = 52,036 section leaves + 2 chapter-material records
       + 8 typed chapter terminals
```

The only prospective Washington ledger is
`full-acquisition-evidence-v15-wa-v1/WA`. It contains 4,423 unique fetch
receipts:

```text
4,423 = 1 root + 101 titles + 2,785 chapters + 1,536 sections
```

The current parser classifies all 1,536 retained section pages as
operative, with zero section terminals. No chapter-catalog heading
matches the strict section-terminal vocabulary, so none of the remaining
pages can be skipped by inferring a lifecycle status from its heading.

Retained-vs-residual leaf algebra for the 52,036 section leaves is:

```text
52,036 = 1,536 known operative + 0 known terminal + 50,500 unresolved
```

The residual is that source-ordered difference. It is not a guessed later
`cite=` continuation, a merge with Minnesota or Missouri residuals, a
Wayback CDX expansion, or a bounded sample.

Do not seed `catalog-first/WA`, `staging-wa-v1` through `staging-wa-v10`,
or the two shared-cache RCW entries (`1.20.051` and `1.20.055`). Those
cache bodies have older, conflicting digests and cannot replace the
retained current bytes. Seed only strict v15 into a fresh immutable
evidence root.

## Exact first and last residual locators

The first residual member is not an inferred next cite after the last
retained section, a guessed Title 7 continuation, or a later URL invented
from `7.05.231`. It is the first source-ordered section leaf absent from
the 1,536 retained section URLs:

```text
https://app.leg.wa.gov/RCW/default.aspx?cite=7.05.230
```

That URL is `washington_section.section_url("7.05.230")`. The last residual
member is the same construction for the final unresolved identity:

```text
https://app.leg.wa.gov/RCW/default.aspx?cite=91.08.900
```

A later residual SHA may be recomputed only from the source-ordered unique
URL array after a v15 catalog replay minus those 1,536 retained endpoints.
It must still start with `e41a7baf281a` or record a newly hashed equal
count from a drifted official catalog. Guessing the remaining hex,
inventing `7.05.231` or `99.99.999`, or substituting a static URL list
fails closed.

## One global residual wave

The adapter already submits the complete cross-chapter leaf union once
as `section-frontier`. Root, title, and chapter discovery remain three
dependency-ordered plural waves because each level supplies the next
level's exact identities. Parsing and the 256-row checkpoint slice remain
bounded but must not fragment transport into separate archive request
waves.

Required acquisition shape:

1. Seed verified direct v15 inputs into a fresh absent evidence root
   (`--allowed-source-transport direct`; hardlinks, `copied_file_count=0`).
2. Replay retained root, 101 titles, and 2,785 chapter catalogs from that
   ledger.
3. Submit the complete source-ordered 52,036-leaf union as one plural
   batch named `section-frontier`. Retained replay covers 1,536 section
   inputs. The unresolved remainder is the 50,500-URL residual.
4. Use one `app.leg.wa.gov` Common Crawl inventory with URL term `/RCW/`,
   grouped/coalesced WARC reuse, and Wayback prefix inventory.
   Residual-only retries must not repeat grouped archive inventory.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require 54,923 inputs, first/replay frontier equality, closed
   operative/terminal algebra over the 52,046 source-outcome units, and
   `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists or sample caps;
- guessed later `cite=` URLs, including `7.05.231` and `99.99.999`;
- merging Washington residuals with Minnesota, Missouri, or any other
  jurisdiction residual;
- per-page archive loops and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming a fenced staging root (`staging-wa-v1` through
  `staging-wa-v10`) or the receiptless `catalog-first/WA` snapshot as
  current;
- stamping historical archive bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Washington binding |
|---|---|
| Source-derived frontier | Official RCW root title order plus chapter-catalog section identities |
| Fresh evidence generation | Seed only strict v15; never overwrite v15 or promote staging-wa-v1–v10 |
| Direct-only reuse | `--allowed-source-transport direct` |
| One residual wave | unresolved remainder of `section-frontier`, 50,500 URLs |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual wave closes:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states WA \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-wa-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-wa-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the first residual member:

```text
https://app.leg.wa.gov/RCW/default.aspx?cite=7.05.230
```

The exact remaining proof residual is the complete 50,500-URL ordered
section wave from that locator through
`https://app.leg.wa.gov/RCW/default.aspx?cite=91.08.900` at SHA prefix
`e41a7baf281a`.
