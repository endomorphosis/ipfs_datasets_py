# Kentucky residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-090`  
Goal: `LCR-G150`  
Track: `exact51-residual-wave-a`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-090 by recording the exact remaining Kentucky unique
leaf residual after the v4 retained root and chapter catalogs. Host
zero-network replay has not sealed a current-bundle pair. The six
closed-state steps remain the only admitted path. Hub mutation, a static
residual list, a per-page archive loop, double-counting duplicate
exact-request groups, and replaying mixed historical request identities as
current are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | KY |
| official domain | apps.legislature.ky.gov |
| official entry | `https://apps.legislature.ky.gov/law/statutes/` |
| official_section_locator | `https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=` |
| official_chapter_locator | `https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | official KRS root/chapter/section HTML-or-PDF tree |
| seed | v4 unique request/URL identities; duplicate exact-request groups preserved |
| duplicate_exact_request_groups | preserved_never_double_counted |
| mixed_historical_request_identities_as_current | forbidden |
| wayback_current_without_equivalence_proof | forbidden |
| static_residual_list | forbidden |
| invent_later_statute_ids | forbidden |
| numeric_id_range_membership | forbidden |
| unique_source_ordered_leaves | 40569 |
| retained_root_pages | 1 |
| retained_chapter_catalogs | 753 |
| retained_unique_leaves | 28928 |
| unique_request_url_identities | 29682 |
| v4_receipts | 29854 |
| duplicate_exact_request_extra_receipts | 172 |
| unique_content_objects | 29670 |
| unique_content_object_bytes | 238948779 |
| v4_direct_receipts | 29839 |
| v4_wayback_receipts | 15 |
| parser_input_frontier | 41323 |
| residual_count | 11641 |
| residual_kind | unique ordered statute.aspx leaves |
| residual_first_source_record_id | kentucky-statute-29404 |
| residual_last_source_record_id | kentucky-statute-20428 |
| residual_first_url | `https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=29404` |
| residual_last_url | `https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=20428` |
| residual_ordered_sha256_prefix | `c96072a16cc6` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_wave_name | `section` |
| catalog_wave_name | `chapter-index` |
| root_wave_name | `root-index` |
| hierarchy_wave_count | 2 |
| leaf_acquisition_wave_count | 1 |
| request_batch_count | 3 |
| source_ordered_cross_parent_union | true |
| unique_url_residual | true |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| replay_only_request_identities | exact plain GET then legacy Accept header |
| live_residual_request_identity | shared plural ordinary GET |
| legacy_accept_header | `text/html,application/pdf,*/*;q=0.8` |
| source_bundle_prefix | `7ee7c0ed8855` |
| diagnostic_producer | `KentuckyScraper@sha256:7ee7c0ed8855` |
| diagnostic_hashes_authorizing | false |

The residual SHA-256 prefix `c96072a16cc6` is the already published identity
of the source-ordered unique 11,641-URL leaf difference. Guessing the
remaining hex, emitting an 11,641-URL dump, treating duplicate exact-request
groups as extra residual members, or inventing a numeric `statute.aspx?id=`
range from 29404 through 20428 fails closed. This report does not emit the
11,641 URLs: a static dump would be a forbidden residual list and would
exceed the compact-recipe admission bound. The last locator is source-ordered,
not numerically later than the first.

## Outcome

Kentucky is **not** assembler-eligible. Hierarchy membership is known, the
v4 unique request/URL identities are known, and the remaining leaf wave is
an exact 11,641-URL unique residual. No host retained-replay seal,
normalized receipt, JSON-LD/Parquet pair, or current-bundle pair exists for
this observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one global unique-leaf wave against
a fresh seed of the v4 unique identities, preserving duplicate
exact-request groups without double-counting, then host
`--retained-replay-only` of every parser input with zero network before
materialization.

## Unique-leaf and duplicate-request algebra

Strict lifecycle derives 40,569 unique source-ordered leaves from one
retained official root plus 753 retained chapter catalogs. Those catalogs
are official `chapter.aspx?id=` units, including nested subchapters and
Kentucky Rules of Evidence units. Concurrent official records that share a
printed section number remain distinct leaves because each has its own
`statute.aspx?id=` source-record identity.

The v4 ledger has 29,854 receipts but only 29,682 unique request/URL
identities:

```text
29,682 unique request/URL identities
  = 1 root
  + 753 chapter catalogs
  + 28,928 unique retained leaves

29,854 receipts
  = 29,682 unique identities
  + 172 extra receipts in duplicate exact-request groups
```

Every duplicate exact-request group binds byte-identical content. The extra
172 receipts are preserved in the ledger and skipped at seed selection
(`duplicate_request_observations_avoided`). They are never reacquired and
never counted as additional unique residual URLs.

All 29,670 content-addressed objects (238,948,779 bytes) pass fixity with
zero missing/orphan objects, unsafe paths, request conflicts, endpoint
conflicts, or unexpected URLs. Transport is 29,839 direct plus 15 Wayback
receipts:

```text
29,854 receipts = 29,839 direct + 15 Wayback
```

The 15 Wayback receipts are not unique residual members. They remain
diagnostics unless an explicit current-equivalence proof exists for that
exact URL and byte identity. Direct-only seed skips unverifiable Wayback
receipts; it does not convert them into extra unique leaves.

The complete parser-input frontier and unique-leaf residual are:

```text
41,323 = 1 root + 753 chapters + 40,569 unique leaves
11,641 = 40,569 unique leaves - 28,928 retained unique leaves
```

The residual is that source-ordered unique-URL difference. It is not a
numeric id hunt from 29404 to 20428, a second copy of a duplicate
exact-request group, or a mixed plain-GET plus Accept-header pair for one
URL.

## Mixed historical request identities

Early Kentucky evidence used the adapter's explicit `Accept` header
(`text/html,application/pdf,*/*;q=0.8`) in its sanitized request identity.
Later shared plural fetches use the ordinary GET contract
`{"method": "GET", "url": ...}`. Those two shapes are historical request
identities for the same official URL. They are not two current residual
members.

Retained-replay-only mode probes both known variants before declaring a
miss: the exact plain GET and the legacy Accept-header GET. Live residual
routing is unchanged: retained Accept-header hits are reused, and genuine
misses are submitted once through the shared plural ordinary-GET wave.
Do not replay mixed historical request identities as current, do not
acquire the same unique URL twice because both identities exist, and do
not stamp a Wayback body current without an equivalence proof.

## Exact remaining URL

The exact next URL is the first source-ordered unique leaf absent from the
28,928 retained unique leaf identities:

```text
https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=29404
```

The last source-ordered unique residual locator is:

```text
https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=20428
```

Those locators are official `statute.aspx?id=` source-record identities
derived from retained chapter catalogs. They are not inferred from a
numeric range, from a guessed later `id=29405`, or from a bounded live
seed. The source-record ids are `kentucky-statute-29404` through
`kentucky-statute-20428` in source order.

The exact remaining proof residual is the complete 11,641-URL ordered
unique-leaf difference at SHA prefix `c96072a16cc6`. Recompute that array
only from the source-ordered unique section union minus retained unique
leaf endpoints. A later residual SHA may be recorded only after that
derivation and must use
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## One catalog wave, then one global unique-leaf wave

The adapter already submits the official root as `root-index`, the complete
chapter-unit union as `chapter-index`, and the complete cross-chapter
descendant union as one `section` wave. After a seed of the v4 unique
identities, the unresolved remainder of `section` is the exact 11,641-URL
unique residual. Residual retries do not repeat grouped archive inventory.
Do not invent a second per-page, per-chapter, or CDX loop.

Required acquisition shape:

1. Seed the v4 unique request/URL identities into a fresh absent evidence
   root (`--allowed-source-transport direct`; hardlinks,
   `copied_file_count=0`). Preserve duplicate exact-request groups in the
   source ledger; select one observation per exact request identity; never
   double-count the 172 extra receipts as extra unique URLs.
2. Replay the retained official root and 753 chapter catalogs. Require
   `29,682 = 1 + 753 + 28,928` unique identities before the residual wave.
3. Submit the complete source-ordered unique leaf union as one plural batch
   named `section`. Retained replay covers the 28,928 unique leaves. The
   unresolved remainder is the 11,641-URL residual named by SHA prefix
   `c96072a16cc6`. Concurrent official records remain distinct because each
   has its own `statute.aspx?id=`.
4. Use one `apps.legislature.ky.gov` Common Crawl inventory with URL term
   `/law/statutes/`, grouped/coalesced WARC reuse, and Wayback prefix
   inventory. Residual-only retries must not repeat grouped archive
   inventory.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Probe both the exact plain GET and the legacy Accept-header
   identity before a miss. Require first/replay frontier equality, unique
   leaf algebra `40,569 = 28,928 + 11,641`, and
   `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later
  `statute.aspx?id=` locators;
- treating a numeric id range from 29404 through 20428 as residual
  membership;
- double-counting duplicate exact-request groups or mixed historical
  request identities as extra unique leaves;
- replaying mixed historical request identities as current;
- treating 15 Wayback bodies as current without an explicit
  current-equivalence proof for that exact URL and byte identity;
- per-page archive loops, per-chapter CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming a fenced staging root as current.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Kentucky binding |
|---|---|
| Source-derived frontier | Official KRS root plus chapter catalogs, then unique `statute.aspx?id=` leaves |
| Fresh evidence generation | Seed v4 unique identities; preserve duplicate exact-request groups; never double-count |
| Direct-only reuse | `--allowed-source-transport direct` |
| One residual wave | unresolved remainder of `section` (11,641 unique leaves) |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual wave closes:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states KY \
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
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-ky-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-ky-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the first unique residual leaf:

```text
https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=29404
```

The exact remaining proof residual is the complete 11,641-URL ordered
unique-leaf wave at SHA prefix `c96072a16cc6`, with duplicate
exact-request groups preserved and never double-counted.
