# Vermont residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-097`  
Goal: `LCR-G152`  
Track: `exact51-residual-wave-c`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-097 by recording the exact remaining Vermont
residual: start from a fresh official root at
`https://legislature.vermont.gov/statutes/`, then acquire the 46
source-ordered statutory titles (floor 47 requests). Host zero-network
replay has not sealed a current-bundle pair. The six closed-state steps
remain the only admitted path. Hub mutation, a static residual list, a
per-page archive loop, resuming the still-absent `staging-vt-v1` or
`full-acquisition-evidence-v19-vt-v1` roots as current, importing the
receiptless May generic cache as authorizing evidence, and admitting
obsolete repaired-static identities `10A`, `16A`, or `24A` are not
admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | VT |
| official domain | legislature.vermont.gov |
| official entry | `https://legislature.vermont.gov/statutes/` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | official HTML tree root → title → chapter → optional subchapter/article → section |
| seed | zero authorizing current-ledger inputs; start from absent staging-vt-v1 and full-acquisition-evidence-v19-vt-v1 |
| start_from_absent_staging_roots | true |
| resume_staging_vt_v1 | forbidden |
| resume_full_acquisition_evidence_v19_vt_v1 | forbidden |
| import_may_generic_cache | forbidden |
| import_catalog_first_repaired_json | forbidden |
| legacy_insecure_tls_authorizing | forbidden |
| static_residual_list | forbidden |
| invent_later_title_targets | forbidden |
| obsolete_repaired_title_ids | 10A, 16A, 24A forbidden |
| per_page_archive_loop | false |
| retained_strict_parser_inputs | 0 |
| diagnostic_root_bytes | 60954 |
| diagnostic_root_sha256 | `108a4010a1a2ceb7e72d7051d902c812dabbed6efe62a36ee93bc553ab2468c9` |
| diagnostic_root_authorizing | false |
| diagnostic_title_count | 46 |
| diagnostic_title_id_sha256 | `2955d0d4679a05d164c8bfff9a3357cbd69db76dfe01c387cb15c5b42f928d56` |
| diagnostic_title_url_sha256 | `c103bbe938a745dc394f9c337ed12145d90038f94e2a0bcbd7718a4eb81b4266` |
| diagnostic_title_id_sha256_prefix | 2955d0d4679a |
| diagnostic_title_url_sha256_prefix | c103bbe938a7 |
| catalog_first_reported_units | 45 |
| catalog_first_bundle_closed | false |
| catalog_first_authorizing | false |
| may_cache_entries | 7438 |
| may_cache_bytes | 443382994 |
| may_cache_root_pages | 1 |
| may_cache_title_pages | 12 |
| may_cache_chapter_pages | 491 |
| may_cache_section_pages | 6934 |
| may_cache_sha_conflicts | 129 |
| may_cache_transport_evidence | absent |
| may_cache_authorizing | false |
| appendix_title_ids | 3APPENDIX, 10APPENDIX, 16APPENDIX, 24APPENDIX |
| constitution_in_corpus | false |
| regulations_in_corpus | false |
| court_rules_in_corpus | false |
| title_membership_count | 46 |
| chapter_membership_count | source_dependent_after_46_titles |
| subchapter_membership_count | source_dependent_after_46_titles |
| section_membership_count | source_dependent_after_46_titles |
| residual_count | 47 |
| residual_floor | 47 |
| residual_kind | fresh official root plus 46 source-ordered titles |
| residual_first_url | `https://legislature.vermont.gov/statutes/` |
| residual_first_title_url | `https://legislature.vermont.gov/statutes/title/01` |
| residual_last_title_url | `https://legislature.vermont.gov/statutes/title/33` |
| residual_wave_name | `root-index` |
| title_wave_name | `title-index` |
| chapter_wave_name | `chapter-index` |
| subchapter_wave_name | `subchapter-index` |
| section_wave_name_prefix | `sections-` |
| root_acquisition_wave_count | 1 |
| title_acquisition_wave_count | 1 |
| fetch_root_before_titles | true |
| fetch_titles_before_chapters | true |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_ordered_sha256_prefix | fresh_root_plus_46_titles_legislature_vermont_gov |
| source_bundle_prefix | `897c6c17ecb5` |
| diagnostic_producer | `VermontScraper@sha256:897c6c17ecb5654576bfb7b168f6d30f26a0b58948622132275e4d1d32acba91` |
| diagnostic_hashes_authorizing | false |

The residual SHA-256 prefix `fresh_root_plus_46_titles_legislature_vermont_gov`
names the 47-request floor: one official `GET` of
`https://legislature.vermont.gov/statutes/` plus the 46 source-ordered
title URLs whose diagnostic identity is SHA
`c103bbe938a745dc394f9c337ed12145d90038f94e2a0bcbd7718a4eb81b4266`.
Recompute any later residual digest only from that exact current-host
GET identity and from title URLs derived after the fresh root closes,
using `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.
This report does not emit a 46-title URL dump: a static dump would be a
forbidden residual list and would exceed the compact-recipe admission
bound. Chapter, optional subchapter/article, and section counts remain
source-dependent on those 46 title pages and are therefore not
predeclared integers.

## Outcome

Vermont is **not** assembler-eligible. No authorizing current-host
ledger exists. A 60,954-byte `/statutes/` root payload at SHA
`108a4010a1a2ceb7e72d7051d902c812dabbed6efe62a36ee93bc553ab2468c9`
replays offline to 46 source-ordered statutory titles, Title 1 through
Title 33, including `3APPENDIX`, `10APPENDIX`, `16APPENDIX`, and
`24APPENDIX`. That diagnostic root is **not** a strict parser input.
Both intended `staging-vt-v1` and `full-acquisition-evidence-v19-vt-v1`
roots were absent at audit time, so exact strict-reusable parser inputs
are zero. No host retained-replay seal, normalized receipt,
JSON-LD/Parquet pair, or current-bundle pair exists for a current-root
observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is to allocate those still-absent
evidence roots, request and retain
`https://legislature.vermont.gov/statutes/` first, recompute title
membership from that payload, submit the 46 derived title pages as one
same-domain plural wave, then continue source-ordered chapter,
optional subchapter/article, and section waves, and finally host
`--retained-replay-only` with zero network before materialization.

## Fresh root plus 46 titles, not the May cache or catalog-first repair

The official live Vermont Statutes Annotated tree lives at
`legislature.vermont.gov`. Strict scope is only root → title → chapter →
optional subchapter/article → section. The Vermont Constitution,
regulations and administrative rules, court rules, and editorial or
secondary presentations are outside this corpus.

The diagnostic 60,954-byte root proves 46 titles. Ordered title-ID SHA
is `2955d0d4679a05d164c8bfff9a3357cbd69db76dfe01c387cb15c5b42f928d56`.
Ordered canonical-title-URL SHA is
`c103bbe938a745dc394f9c337ed12145d90038f94e2a0bcbd7718a4eb81b4266`.
Obsolete repaired-static identities `10A`, `16A`, and `24A` are absent
from that observation; the live appendix identities are `3APPENDIX`,
`10APPENDIX`, `16APPENDIX`, and `24APPENDIX`. Those diagnostic hashes
are not authorizing. Do not import them as a sealed current-bundle
pair.

The catalog-first material is nonauthorizing: its derived frontier
incorrectly reports 45 units, its body is repaired JSON,
`bundle_closed=false`, and its referenced receipt is absent.

The May legacy cache is also nonauthorizing and regression-only: 7,438
distinct URL/body entries over 443,382,994 bytes (one root, 12 titles,
491 chapters, and 6,934 sections) claim `requests_direct` but contain
no origin `transport_evidence`. Full rehash finds 129 metadata/body SHA
conflicts (11 chapter bodies plus 118 section bodies). As a parser
oracle only, the 491 chapter bodies expose 6,954 unique labelled
section URLs, leaving 20 old Title 10 Chapter 119 residuals; the 6,934
cached section bodies classify as 6,122 operative plus 812 typed
terminals. None of those bytes may seed a current evidence root.

Required current-root algebra after the fresh GET succeeds:

```text
1 current-root GET
  → 46 titles = source-ordered Title 1 through Title 33,
    including 3APPENDIX, 10APPENDIX, 16APPENDIX, 24APPENDIX
  → chapter catalogs derived only from those 46 title pages
  → optional subchapter/article catalogs derived only from those chapters
  → section locators and bodies derived only from those catalogs
```

Title membership is the 46-unit diagnostic identity unless the fresh
root fails catalog parity. Chapter, subchapter/article, and section
counts are unknown until those 46 title pages are retained. Guessing
them from the May cache, from the catalog-first 45-unit repair, or from
invented `10A` / `16A` / `24A` locators fails closed.

## Exact remaining URL

The exact next URL is the current official root:

```text
https://legislature.vermont.gov/statutes/
```

That locator is the live General Assembly statutes index. It is not a
May generic-cache identity, not the catalog-first repaired JSON, not
`/statutes/title/10A`, and not a constitution, regulation, or court-rule
path.

The 46 title residual then starts at
`https://legislature.vermont.gov/statutes/title/01` and ends at
`https://legislature.vermont.gov/statutes/title/33`, including appendix
identities such as
`https://legislature.vermont.gov/statutes/title/03APPENDIX` and excluding
obsolete `10A`, `16A`, and `24A`.
Do not emit those 46 URLs as a static list. Derive them from the fresh
root payload. The adapter already binds live/static title catalog
parity and fails closed on a missing, extra, or renamed title.

The exact remaining proof residual is:

1. The one-URL current-root wave `root-index` at
   `https://legislature.vermont.gov/statutes/`.
2. The one global source-ordered title wave `title-index` of 46 pages
   whose diagnostic URL SHA is `c103bbe938a745…`.
3. Chapter, optional subchapter/article, and section membership whose
   counts remain source-dependent on those 46 title pages.

Together that is the 47-request floor. Recompute any later residual SHA
only from source-ordered URLs derived after the current root closes,
using `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## One root wave, then one title wave, then source-derived descendants

The adapter already reconstructs the official tree as ordered plural
waves: `root-index`, `title-index`, `chapter-index`, optional
`subchapter-index`, then `sections-*`. After a fresh absent evidence
root, the unresolved first remainder is exactly the current-host
`/statutes/` GET. Titles must close from that payload before any
chapter, subchapter, or section union is submitted. Residual retries
do not repeat grouped archive inventory. Do not invent a second
per-title, per-chapter, per-page, or CDX loop. Do not call the legacy
insecure-TLS helper; verified-direct failure proceeds through the
shared archival fallback, and the diagnostic TLS bypass cannot
authorize publication.

Required acquisition shape:

1. Allocate the still-absent evidence roots
   `staging-vt-v1` and `full-acquisition-evidence-v19-vt-v1`. Destination
   jurisdiction directories must be absent (`copied_file_count=0`). Do
   not import the May generic cache or the catalog-first repaired JSON.
2. Request and retain `https://legislature.vermont.gov/statutes/` first
   as one plural `root-index` wave (`--allowed-source-transport direct`).
   Prefer direct. Validate the payload (`Vermont`, `statute`, HTML, no
   404/moved body). Recompute ordered title identity and URL
   projections. Stop on any duplicate, identity mismatch, obsolete
   `10A`/`16A`/`24A` extra, or missing appendix identity.
3. Submit the newly derived 46-title frontier as one same-domain
   plural `title-index` wave. The default 512-page VT frontier batch
   keeps a 46-title catalog in one logical inventory. Validate live
   catalog parity against the official title set.
4. Only after fresh title closure, derive chapter URLs in source order
   and continue bounded plural `chapter-index` waves, then optional
   `subchapter-index` (including `/statutes/article/` locators), then
   section locators and bodies as `sections-*` waves. Do not open one
   HTTP client or archive inventory per page.
5. Use one `legislature.vermont.gov` Common Crawl inventory with URL
   term `/statutes/`, grouped/coalesced WARC reuse, and Wayback prefix
   inventory. Residual-only retries must not repeat grouped archive
   inventory. Common Crawl inventory may be memoized only when the
   options match; that is not a claim of one physical inventory for an
   unbounded crawl.
6. Host-replay every parser input with `--retained-replay-only` and
   zero network. Require first/replay frontier equality and
   `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later
  `/statutes/title/{id}` targets, including obsolete `10A`, `16A`, and
  `24A`;
- importing the receiptless May generic cache as authorizing evidence;
- importing the catalog-first repaired JSON (45 units,
  `bundle_closed=false`, absent receipt) as authorizing evidence;
- resuming `staging-vt-v1` or `full-acquisition-evidence-v19-vt-v1` as
  current if they remain absent, or seeding a destination that already
  exists;
- treating the diagnostic 60,954-byte root as a strict-reusable parser
  input;
- per-page archive loops, per-title CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- authorizing publication through the diagnostic insecure-TLS bypass;
- admitting the Vermont Constitution, regulations/admin rules, court
  rules, or editorial/secondary presentations into this statutory
  corpus;
- submitting titles, chapters, subchapters, or sections before the
  current root closes.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Vermont binding |
|---|---|
| Source-derived frontier | Fresh `legislature.vermont.gov` `/statutes/`, then 46 titles, chapters, optional subchapters/articles, sections |
| Fresh evidence generation | Absent `staging-vt-v1` and `full-acquisition-evidence-v19-vt-v1`; never import the May cache |
| Direct-only reuse | `--allowed-source-transport direct` |
| Current-root residual | `root-index`, 1 URL, then `title-index` of 46 |
| Title remainder | 46; diagnostic URL SHA `c103bbe938a745…` |
| Chapter/subchapter/section remainder | source-dependent after the 46 titles close |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual waves close:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states VT \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-vt-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-vt-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is `https://legislature.vermont.gov/statutes/`.
Inventing a later `/statutes/title/10A`, importing the May generic
cache, or treating the catalog-first 45-unit repair as current fails
closed.

The exact remaining proof residual is that one-URL current-root wave
plus the 46 source-ordered titles (floor 47 requests) at SHA prefix
`fresh_root_plus_46_titles_legislature_vermont_gov`, whose diagnostic
title-URL identity is `c103bbe938a745…`, then the complete
source-ordered chapter, optional subchapter/article, and section
membership whose counts remain source-dependent on those titles.
