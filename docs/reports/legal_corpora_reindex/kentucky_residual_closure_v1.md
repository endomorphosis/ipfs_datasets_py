# Kentucky residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-090`  
Goal: `LCR-G150`  
Track: `exact51-residual-wave-a`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-090 by recording both the original all-transport v4
diagnostic residual and the authorizing direct-only current-live residual after
the retained root and chapter catalogs. Host
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
| seed | v4 direct-only projection; duplicate exact-request groups preserved in the source generation and never double-counted |
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
| residual_scope | original all-transport v4 diagnostic |
| residual_kind | unique ordered statute.aspx leaves |
| residual_first_source_record_id | kentucky-statute-29404 |
| residual_last_source_record_id | kentucky-statute-20428 |
| residual_first_url | `https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=29404` |
| residual_last_url | `https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=20428` |
| residual_ordered_sha256_prefix | `c96072a16cc6` |
| residual_ordered_sha256 | `c96072a16cc6cf0def74d7d2d6b5a7420c936a5a28b7b35ffe2f2ec36da5cac1` |
| direct_seed_selected_parser_inputs | 29675 |
| direct_seed_unique_content_objects | 29663 |
| direct_seed_duplicate_request_observations_avoided | 164 |
| direct_seed_skipped_wayback_receipts | 15 |
| direct_seed_retained_unique_leaves | 28921 |
| current_live_residual_count | 11648 |
| current_live_residual_first_source_record_id | kentucky-statute-25144 |
| current_live_residual_last_source_record_id | kentucky-statute-20428 |
| current_live_residual_ordered_sha256 | `f2a7625b4f93fdb1fd05615c8e1e1a84c7e947870322995a1396de786e2a38bf` |
| wayback_only_current_reacquisition_ids | 25144, 25481, 25491, 25501, 43841, 5613, 5626 |
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
| retained_request_identity_order | exact legacy Accept-header GET then plain GET, in live and replay-only modes |
| live_residual_request_identity | shared plural plain GET |
| legacy_accept_header | `text/html,application/pdf,*/*;q=0.8` |
| source_bundle_prefix | `7ee7c0ed8855` |
| diagnostic_producer | `KentuckyScraper@sha256:7ee7c0ed8855` |
| diagnostic_hashes_authorizing | false |

The residual SHA-256
`c96072a16cc6cf0def74d7d2d6b5a7420c936a5a28b7b35ffe2f2ec36da5cac1`
is the already published identity of the source-ordered unique 11,641-URL leaf
difference when all v4 transports are counted. It is a diagnostic identity,
not the authorizing live request set. Guessing the
remaining hex, emitting an 11,641-URL dump, treating duplicate exact-request
groups as extra residual members, or inventing a numeric `statute.aspx?id=`
range from 29404 through 20428 fails closed. This report does not emit the
11,641 URLs: a static dump would be a forbidden residual list and would
exceed the compact-recipe admission bound. The last locator is source-ordered,
not numerically later than the first.

## Outcome

Kentucky is **not** assembler-eligible. Hierarchy membership is known, the
v4 identities are known, and the direct-only authorizing seed leaves an exact
11,648-URL current-live residual. That set is the original 11,641-URL
all-transport diagnostic difference plus seven exact leaves whose only v4
receipts were Wayback and therefore cannot be reused as current. No host
retained-replay seal,
normalized receipt, JSON-LD/Parquet pair, or current-bundle pair exists for
this observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one global unique-leaf wave against
a fresh seed of the v4 direct-only identities, preserving duplicate
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

The 15 Wayback receipts remain diagnostics unless an explicit
current-equivalence proof exists for the exact URL and byte identity. The
direct-only seed skips all 15. Eight are extra observations of URLs already
present under direct transport; the other seven are the only v4 observations
for source-record ids `25144`, `25481`, `25491`, `25501`, `43841`, `5613`, and
`5626`. Those seven are not promoted from Wayback: they become exact required
current reacquisitions.

The complete parser-input frontier and unique-leaf residual are:

```text
41,323 = 1 root + 753 chapters + 40,569 unique leaves
11,641 = 40,569 unique leaves - 28,928 all-transport retained unique leaves
29,675 direct seed identities = 1 root + 753 chapters + 28,921 direct leaves
11,648 current-live residual = 40,569 unique leaves - 28,921 direct leaves
11,648 = 11,641 original all-transport residual + 7 Wayback-only replacements
```

The authorizing acquisition residual is the 11,648-member direct-only
source-ordered unique-URL difference, SHA-256
`f2a7625b4f93fdb1fd05615c8e1e1a84c7e947870322995a1396de786e2a38bf`.
It is not a
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

Live and retained-replay-only modes probe both known variants in one
deterministic order before declaring a miss: the legacy Accept-header GET
first, then the plain GET. Plain GET is the shared current plural-fetch
identity. Because the fresh seed contains only verified direct receipts, a
retained plain hit is current-reusable; a Wayback-only identity is absent and
must be reacquired. Genuine misses are submitted once through the shared
plural plain-GET wave.
Do not replay mixed historical request identities as current, do not
acquire the same unique URL twice because both identities exist, and do
not stamp a Wayback body current without an equivalence proof.

## Exact residual boundaries

The first URL in the original 11,641-member all-transport diagnostic residual
is:

```text
https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=29404
```

The first URL in the authorizing direct-only 11,648-member current-live
residual is:

```text
https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=25144
```

The last source-ordered locator in both residuals is:

```text
https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=20428
```

Those locators are official `statute.aspx?id=` source-record identities
derived from retained chapter catalogs. They are not inferred from a
numeric range, from a guessed later `id=29405`, or from a bounded live
seed. The source-record ids are `kentucky-statute-29404` through
`kentucky-statute-20428` in source order.

The original proof residual is the complete 11,641-URL ordered unique-leaf
difference at SHA-256
`c96072a16cc6cf0def74d7d2d6b5a7420c936a5a28b7b35ffe2f2ec36da5cac1`.
The authorizing direct-only acquisition residual is the 11,648-URL difference
at SHA-256
`f2a7625b4f93fdb1fd05615c8e1e1a84c7e947870322995a1396de786e2a38bf`.
Recompute either array only from the source-ordered unique section union minus
the applicable retained unique leaf endpoints. The digest method is
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## One catalog wave, then one global unique-leaf wave

The adapter already submits the official root as `root-index`, the complete
chapter-unit union as `chapter-index`, and the complete cross-chapter
descendant union as one `section` wave. After the v4 direct-only seed, the
unresolved remainder of `section` is the exact 11,648-URL current-live
residual: the documented 11,641 plus seven Wayback-only current
reacquisitions. Residual retries do not repeat grouped archive inventory.
Do not invent a second per-page, per-chapter, or CDX loop.

Required acquisition shape:

1. Seed the v4 direct-only request/URL identities into a fresh absent evidence
   root (`--allowed-source-transport direct`; hardlinks,
   `copied_file_count=0`). Preserve duplicate exact-request groups in the
   source ledger; select one observation per exact request identity; never
   double-count the 172 extra receipts as extra unique URLs.
2. Replay the retained official root and 753 chapter catalogs. Require the
   direct seed identity algebra `29,675 = 1 + 753 + 28,921` before the
   residual wave.
3. Submit the complete source-ordered unique leaf union as one plural batch
   named `section`. Retained direct replay covers 28,921 unique leaves. The
   unresolved remainder is exactly 11,648 URLs at SHA-256
   `f2a7625b4f93fdb1fd05615c8e1e1a84c7e947870322995a1396de786e2a38bf`.
   Concurrent official records remain distinct because each has its own
   `statute.aspx?id=`.
4. Use one `apps.legislature.ky.gov` Common Crawl inventory with URL term
   `/law/statutes/`, grouped/coalesced WARC reuse, and Wayback prefix
   inventory. Residual-only retries must not repeat grouped archive
   inventory.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Probe the exact legacy Accept-header GET and then the plain GET
   before a miss. Require first/replay frontier equality, direct-only unique
   leaf algebra `40,569 = 28,921 + 11,648`, and
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
| Fresh evidence generation | Seed v4 direct-only identities; preserve duplicate exact-request groups in the source generation; never double-count |
| Direct-only reuse | `--allowed-source-transport direct` |
| One residual wave | unresolved remainder of `section` (11,648 unique leaves: original 11,641 plus seven Wayback-only current replacements) |
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
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-ky-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-ky-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next current-live residual URL

The exact next URL for the authorizing direct-only seed is:

```text
https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=25144
```

The exact current-live residual is the complete 11,648-URL ordered unique-leaf
wave at SHA-256
`f2a7625b4f93fdb1fd05615c8e1e1a84c7e947870322995a1396de786e2a38bf`,
with duplicate exact-request groups preserved in the source generation and
never double-counted. The original all-transport diagnostic residual remains
11,641 URLs at
`c96072a16cc6cf0def74d7d2d6b5a7420c936a5a28b7b35ffe2f2ec36da5cac1`.
