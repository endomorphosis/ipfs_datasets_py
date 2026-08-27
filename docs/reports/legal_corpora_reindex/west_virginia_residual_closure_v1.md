# West Virginia residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-098`  
Goal: `LCR-G152`  
Track: `exact51-residual-wave-c`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-098 by recording the exact remaining West Virginia
residual: start from a fresh official root at
`https://code.wvlegislature.gov/`, then acquire the 139 source-ordered
statutory chapters (floor 140 requests). Host zero-network replay has
not sealed a current-bundle pair. The six closed-state steps remain the
only admitted path. Hub mutation, a static residual list, a per-page
archive loop, resuming the still-absent `staging-wv-v1` or
`full-acquisition-evidence-v20-wv-v1` roots as current, importing
catalog descriptions, singleton artifacts, or source-recovery
experiments as authorizing evidence, and admitting obsolete repaired
Chapter `48A` are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | WV |
| official domain | code.wvlegislature.gov |
| official entry | `https://code.wvlegislature.gov/` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | official HTML tree root → chapter → article → section |
| seed | zero authorizing current-ledger inputs; start from absent staging-wv-v1 and full-acquisition-evidence-v20-wv-v1 |
| start_from_absent_staging_roots | true |
| resume_staging_wv_v1 | forbidden |
| resume_full_acquisition_evidence_v20_wv_v1 | forbidden |
| import_catalog_descriptions | forbidden |
| import_singleton_artifacts | forbidden |
| import_source_recovery_experiments | forbidden |
| import_west_virginia_dump | forbidden |
| legacy_insecure_tls_authorizing | forbidden |
| static_residual_list | forbidden |
| invent_later_chapter_targets | forbidden |
| obsolete_repaired_chapter_ids | 48A forbidden |
| per_page_archive_loop | false |
| retained_strict_parser_inputs | 0 |
| diagnostic_root_bytes | 37628 |
| diagnostic_root_sha256 | `cf36b6769ae…` |
| diagnostic_root_authorizing | false |
| diagnostic_chapter_count | 139 |
| diagnostic_chapter_id_sha256 | `5189c5177146…` |
| diagnostic_chapter_url_sha256 | `6c2473b0371b…` |
| diagnostic_label_sha256 | `b2e241965274…` |
| diagnostic_chapter_id_sha256_prefix | 5189c5177146 |
| diagnostic_chapter_url_sha256_prefix | 6c2473b0371b |
| diagnostic_label_sha256_prefix | b2e241965274 |
| catalog_first_reported_units | 140 |
| catalog_first_bundle_closed | false |
| catalog_first_includes_obsolete_48A | true |
| catalog_first_authorizing | false |
| catalog_first_receipt | absent |
| singleton_artifact_rows | 2 |
| singleton_artifact_sections | 61-2-1, 61-2-2 |
| singleton_artifact_authorizing | false |
| source_recovery_experiments | 12 |
| source_recovery_section | 61-2-9 |
| source_recovery_html_candidates | 8 |
| source_recovery_distinct_digests | 8 |
| source_recovery_transport_receipt | absent |
| source_recovery_authorizing | false |
| legal_page_cache_wv_urls | 0 |
| live_probe_chapter_1_articles | 8 |
| live_probe_article_1_section_locators | 6 |
| live_probe_section_1_1_1_chars | 679 |
| live_probe_authorizing | false |
| display_all_article_sections_scaffold | excluded source-bound UI toggle inside div.sec-head |
| constitution_in_corpus | false |
| court_rules_in_corpus | false |
| editorial_secondary_in_corpus | false |
| chapter_membership_count | 139 |
| article_membership_count | source_dependent_after_139_chapters |
| section_membership_count | source_dependent_after_139_chapters |
| residual_count | 140 |
| residual_floor | 140 |
| residual_kind | fresh official root plus 139 source-ordered chapters |
| residual_first_url | `https://code.wvlegislature.gov/` |
| residual_first_chapter_url | `https://code.wvlegislature.gov/1/` |
| residual_last_chapter_url | `https://code.wvlegislature.gov/64/` |
| residual_wave_name | `root-index` |
| chapter_wave_name | `chapter-index` |
| article_wave_name | `article-index` |
| section_wave_name_prefix | `sections-` |
| root_acquisition_wave_count | 1 |
| chapter_acquisition_wave_count | 1 |
| fetch_root_before_chapters | true |
| fetch_chapters_before_articles | true |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_ordered_sha256_prefix | fresh_root_plus_139_chapters_code_wvlegislature_gov |
| source_bundle_prefix | `3cf4048dd5f3` |
| diagnostic_producer | `WestVirginiaScraper@sha256:3cf4048dd5f3` |
| diagnostic_hashes_authorizing | false |

The residual SHA-256 prefix `fresh_root_plus_139_chapters_code_wvlegislature_gov`
names the 140-request floor: one official `GET` of
`https://code.wvlegislature.gov/` plus the 139 source-ordered chapter
URLs whose diagnostic identity is SHA prefix `6c2473b0371b`. Recompute
any later residual digest only from that exact current-host GET identity
and from chapter URLs derived after the fresh root closes, using
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.
This report does not emit a 139-chapter URL dump: a static dump would be
a forbidden residual list and would exceed the compact-recipe admission
bound. Article and section counts remain source-dependent on those 139
chapter pages and are therefore not predeclared integers.

## Outcome

West Virginia is **not** assembler-eligible. No authorizing current-host
ledger exists. A 37,628-byte `/` root payload at SHA prefix
`cf36b6769ae` replays offline to 139 source-ordered statutory chapters,
Chapter 1 through Chapter 64, including the source-listed alpha chapters
and excluding obsolete Chapter `48A`. That diagnostic root is **not** a
strict parser input. Both intended `staging-wv-v1` and
`full-acquisition-evidence-v20-wv-v1` roots were absent at audit time,
so exact strict-reusable parser inputs are zero. The shared legal page
cache has zero West Virginia URLs. No host retained-replay seal,
normalized receipt, JSON-LD/Parquet pair, or current-bundle pair exists
for a current-root observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is to allocate those still-absent
evidence roots, request and retain
`https://code.wvlegislature.gov/` first, recompute chapter membership
from that payload, submit the 139 derived chapter pages as one
same-domain plural wave, then continue source-ordered article and
section waves, and finally host `--retained-replay-only` with zero
network before materialization.

## Fresh root plus 139 chapters, not catalog descriptions or singleton artifacts

The official live West Virginia Code tree lives at
`code.wvlegislature.gov`. Strict scope is only root → chapter →
article → section. The separately configured Constitution on
`home.wvlegislature.gov`, court and procedure rules, editorial or
secondary presentations, and dump/HTML override paths are outside this
corpus.

The diagnostic 37,628-byte root proves 139 chapters. Ordered chapter-ID
SHA prefix is `5189c5177146`. Ordered canonical-chapter-URL SHA prefix
is `6c2473b0371b`. Ordered label SHA prefix is `b2e241965274`. Obsolete
repaired-static identity `48A` is absent from that observation; the live
catalog has exact ID/name/URL parity with the guarded official chapter
list. Those diagnostic hashes are not authorizing. Do not import them as
a sealed current-bundle pair.

The catalog-first material is nonauthorizing: its derived catalog has
140 repaired description rows including stale Chapter `48A`
(`Enforcement of Family Obligations`), its body is repaired JSON,
`bundle_closed=false`, its referenced receipt is absent, and it contains
no descendant bodies.

The two-row singleton artifact (`§ 61-2-1`, `§ 61-2-2`) is also
nonauthorizing. Twelve old source-recovery experiments concern only
`§ 61-2-9`; eight contain official HTML candidates with eight distinct
digests but no transport receipt. None of those bytes may seed a current
evidence root. Do not import `WEST_VIRGINIA_CODE_HTML` dump files as
authorizing evidence.

A bounded three-page same-domain live probe found eight Chapter 1
articles, six Article 1 section locators, and a successfully parsed
679-character operative `§ 1-1-1` body. It also exposed the official
article template's unlinked `Display all Article 1 Sections` UI toggle
inside `div.sec-head`. That probe is diagnostic only. The adapter
excludes only that exact source-bound scaffold and continues to fail
closed on disguised operative unlinked rows.

Required current-root algebra after the fresh GET succeeds:

```text
1 current-root GET
  → 139 chapters = source-ordered Chapter 1 through Chapter 64,
    including source-listed alpha chapters and excluding 48A
  → article catalogs derived only from those 139 chapter pages
  → section locators and bodies derived only from those articles
```

Chapter membership is the 139-unit diagnostic identity unless the fresh
root fails catalog parity. Article and section counts are unknown until
those 139 chapter pages are retained. Guessing them from catalog-first
descriptions, from the two-row singleton, from `§ 61-2-9` recovery
experiments, or from invented `48A` locators fails closed.

## Exact remaining URL

The exact next URL is the current official root:

```text
https://code.wvlegislature.gov/
```

That locator is the live Legislature code index. It is not a
catalog-first repaired JSON identity, not `§ 61-2-1`, not `§ 61-2-9`,
not `/48A/`, and not a constitution, court-rule, or dump path.

The 139 chapter residual then starts at
`https://code.wvlegislature.gov/1/` and ends at
`https://code.wvlegislature.gov/64/`, including alpha identities such as
`https://code.wvlegislature.gov/5A/` and excluding obsolete `48A`.
Do not emit those 139 URLs as a static list. Derive them from the fresh
root payload. The adapter already binds live/static chapter catalog
parity and fails closed on a missing, extra, or renamed chapter.

The exact remaining proof residual is:

1. The one-URL current-root wave `root-index` at
   `https://code.wvlegislature.gov/`.
2. The one global source-ordered chapter wave `chapter-index` of 139
   pages whose diagnostic URL SHA prefix is `6c2473b0371b`.
3. Article and section membership whose counts remain source-dependent
   on those 139 chapter pages.

Together that is the 140-request floor. Recompute any later residual SHA
only from source-ordered URLs derived after the current root closes,
using `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## One root wave, then one chapter wave, then source-derived descendants

The adapter already reconstructs the official tree as ordered plural
waves: `root-index`, `chapter-index`, `article-index`, then
`sections-*`. After a fresh absent evidence root, the unresolved first
remainder is exactly the current-host `/` GET. Chapters must close from
that payload before any article or section union is submitted. Residual
retries do not repeat grouped archive inventory. Do not invent a second
per-chapter, per-article, per-page, or CDX loop. Do not call the legacy
insecure-TLS helper; verified-direct failure proceeds through the
shared archival fallback, and the diagnostic TLS bypass cannot
authorize publication.

Required acquisition shape:

1. Allocate the still-absent evidence roots
   `staging-wv-v1` and `full-acquisition-evidence-v20-wv-v1`. Destination
   jurisdiction directories must be absent (`copied_file_count=0`). Do
   not import catalog descriptions, the two-row singleton, source-recovery
   experiments, or `WEST_VIRGINIA_CODE_HTML` dumps.
2. Request and retain `https://code.wvlegislature.gov/` first as one
   plural `root-index` wave (`--allowed-source-transport direct`).
   Prefer direct. Validate the payload (`West Virginia Code`, HTML, no
   404/moved body). Recompute ordered chapter identity and URL
   projections. Stop on any duplicate, identity mismatch, obsolete
   `48A` extra, or missing source-listed alpha chapter.
3. Submit the newly derived 139-chapter frontier as one same-domain
   plural `chapter-index` wave. The default 512-page WV frontier batch
   keeps a 139-chapter catalog in one logical inventory. Validate live
   catalog parity against the official chapter set.
4. Only after fresh chapter closure, derive article URLs in source order
   and continue bounded plural `article-index` waves, then section
   locators and bodies as `sections-*` waves. Do not open one HTTP
   client or archive inventory per page. Exclude only the exact
   source-bound `Display all Article N Sections` `div.sec-head` scaffold.
5. Use one `code.wvlegislature.gov` Common Crawl domain inventory,
   grouped/coalesced WARC reuse, and Wayback prefix inventory.
   Residual-only retries must not repeat grouped archive inventory.
   Common Crawl inventory may be memoized only when the options match;
   that is not a claim of one physical inventory for an unbounded crawl.
6. Host-replay every parser input with `--retained-replay-only` and
   zero network. Require first/replay frontier equality and
   `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later
  `/{chapter}/` targets, including obsolete `48A`;
- importing catalog-first repaired JSON (140 units including `48A`,
  `bundle_closed=false`, absent receipt) as authorizing evidence;
- importing the two-row singleton artifact (`§ 61-2-1`, `§ 61-2-2`);
- importing `§ 61-2-9` source-recovery experiments (twelve runs, eight
  official HTML candidates, eight distinct digests, no transport
  receipt);
- importing `WEST_VIRGINIA_CODE_HTML` dump files or the configured
  constitution HTML path as authorizing Code evidence;
- resuming `staging-wv-v1` or `full-acquisition-evidence-v20-wv-v1` as
  current if they remain absent, or seeding a destination that already
  exists;
- treating the diagnostic 37,628-byte root as a strict-reusable parser
  input;
- per-page archive loops, per-chapter CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- authorizing publication through the diagnostic insecure-TLS bypass;
- admitting the West Virginia Constitution, court/procedure rules, or
  editorial/secondary presentations into this statutory corpus;
- submitting chapters, articles, or sections before the current root
  closes.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | West Virginia binding |
|---|---|
| Source-derived frontier | Fresh `code.wvlegislature.gov` `/`, then 139 chapters, articles, sections |
| Fresh evidence generation | Absent `staging-wv-v1` and `full-acquisition-evidence-v20-wv-v1`; never import catalog descriptions, singletons, or recovery experiments |
| Direct-only reuse | `--allowed-source-transport direct` |
| Current-root residual | `root-index`, 1 URL, then `chapter-index` of 139 |
| Chapter remainder | 139; diagnostic URL SHA prefix `6c2473b0371b` |
| Article/section remainder | source-dependent after the 139 chapters close |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual waves close:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states WV \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-materialize \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-wv-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-wv-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is `https://code.wvlegislature.gov/`.
Inventing a later `/48A/`, importing catalog descriptions, importing the
two-row singleton, or treating `§ 61-2-9` source-recovery experiments as
current fails closed.

The exact remaining proof residual is that one-URL current-root wave
plus the 139 source-ordered chapters (floor 140 requests) at SHA prefix
`fresh_root_plus_139_chapters_code_wvlegislature_gov`, whose diagnostic
chapter-URL identity is `6c2473b0371b…`, then the complete
source-ordered article and section membership whose counts remain
source-dependent on those chapters.
