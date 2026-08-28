# Montana residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-089`  
Goal: `LCR-G150`  
Track: `exact51-residual-wave-a`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-089 by recording the exact remaining Montana
direct-only residual after the verified 40,132-input projection. Host
zero-network replay has not sealed a current-bundle pair. The six
closed-state steps remain the only admitted path. Hub mutation, a static
residual list, a per-page archive loop, Title 0 constitution-identity
drift, resuming fenced `staging-mt-v11`, and treating 2016 Wayback bodies
as current without an equivalence proof are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | MT |
| official domain | leg.mt.gov |
| official entry | `https://leg.mt.gov/bills/mca/index.html` |
| official_title0_url | `https://leg.mt.gov/bills/mca/title_0000/chapters_index.html` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | official MCA root/title/chapter/part/section HTML tree |
| seed | verified direct-only projection 40132 |
| resume_fenced_staging_mt_v11 | forbidden |
| v11_35072_checkpoint | output_inadmissible |
| title_0_identity_drift | forbidden |
| wayback_2016_current_without_equivalence_proof | forbidden |
| static_residual_list | forbidden |
| invent_later_lettered_catalogs | forbidden |
| direct_projection_inputs | 40132 |
| direct_projection_bytes | 441443821 |
| direct_projection_sha256 | `6b8d0baca081c937728b75bd9177fa8654f97dc63a1985e797f3a5017915c271` |
| direct_projection_sha256_prefix | 6b8d0baca081 |
| v4_unique_receipts | 40136 |
| v4_direct_receipts | 40132 |
| v4_wayback_receipts | 4 |
| v4_bytes | 441481218 |
| title_pages | 54 |
| statutory_title_catalogs | 53 |
| title_0_constitution_exclusions | 1 |
| title_0_article_catalog_count | 16 |
| title_0_root_content_sha256_prefix | c945f15a4564 |
| title_0_root_receipt_sha256_prefix | 2aed70c22680 |
| title_0_title_content_sha256_prefix | ffd3643dab4e |
| title_0_title_receipt_sha256_prefix | 545e7837b38a |
| known_statutory_chapters | 880 |
| missing_lettered_catalogs | 5 |
| missing_lettered_catalog_ids | 25-030A, 30-002A, 30-004A, 30-009A, 30-012A |
| retained_parts | 4063 |
| known_leaves | 44433 |
| typed_terminals | 14418 |
| active_candidates | 30015 |
| direct_retained_active_leaves | 23363 |
| residual_active_leaves | 6652 |
| all_transport_retained_active_leaves | 23366 |
| all_transport_residual_active_leaves | 6649 |
| wayback_2016_only_active_sections | 39-71-2319, 39-71-2325, 39-71-2328 |
| source_typed_repealed_near_wayback_actives | 39-71-2324 |
| known_request_floor | 6657 |
| catalog_descendant_count | source_dependent_after_five_catalogs |
| residual_count | 6657 |
| residual_kind | five missing lettered chapter catalogs then unique ordered active leaves plus catalog descendants |
| residual_first_url | `https://leg.mt.gov/bills/mca/title_0250/chapter_030A/parts_index.html` |
| residual_last_missing_catalog_url | `https://leg.mt.gov/bills/mca/title_0300/chapter_012A/parts_index.html` |
| catalog_wave_name | `chapter-index` |
| residual_wave_name | `section` |
| part_wave_name | `part-index` |
| title_wave_name | `title-index` |
| catalog_acquisition_wave_count | 1 |
| leaf_acquisition_wave_count | 1 |
| derive_descendants_of_five_catalogs | true |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_ordered_sha256_prefix | 2af9f839be75 |
| residual_active_leaf_sha256 | `2af9f839be756d401a45a07642d9e7fe1da00ce0bbfdae518c9ef74386450970` |
| all_transport_residual_sha256_prefix | b949f71312a4 |
| diagnostic_producer | `MontanaScraper@sha256:bb4ed1efc8df67db4a6519a9e40b3a95782302a45386b59486c146a0340f7303` |
| diagnostic_hashes_authorizing | false |

The residual SHA-256 prefix `2af9f839be75` is the already published identity
of the source-ordered unique 6,652-URL direct-only active-leaf difference.
The seed projection SHA-256 `6b8d0baca081c937728b75bd9177fa8654f97dc63a1985e797f3a5017915c271`
is the already published identity of the 40,132-input direct-only ledger.
This report does not emit the 6,652 leaf URLs: a static dump would be a
forbidden residual list and would exceed the compact-recipe admission bound.
Descendants of the five missing catalogs remain source-dependent and are
therefore not a predeclared integer.

## Outcome

Montana is **not** assembler-eligible. Direct-only seed membership is known,
the five missing lettered chapter catalogs are known, and the remaining
leaf wave is an exact 6,652-URL active residual plus any newly exposed
descendants of those catalogs. No host retained-replay seal, normalized
receipt, JSON-LD/Parquet pair, or current-bundle pair exists for this
observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one direct-only seed of the
verified 40,132-input projection into a fresh absent evidence root, then
one catalog wave for the five missing lettered chapter catalogs, derive
and acquire their descendants, acquire the 6,652 known active residuals,
then host `--retained-replay-only` of every parser input with zero
network before materialization.

## Direct-only projection algebra

The fully verified v4 ledger is 40,136 unique receipts/objects over
441,481,218 bytes (40,132 direct + four Wayback). Direct-only retention
skips the four unverifiable Wayback receipts and remains exactly 40,132
inputs/objects over 441,443,821 bytes, zero deduplications, projection
SHA `6b8d0baca081c937728b75bd9177fa8654f97dc63a1985e797f3a5017915c271`.

A later seed SHA may be recomputed only from that verified direct
projection. It must still start with `6b8d0baca081` or record a newly
hashed equal count. Guessing the remaining hex or mixing Wayback receipts
into the seed fails closed.

A fresh real-ledger `retained_replay_only` traversal, with acquisition
caches empty and checkpoint writes forbidden, replayed the official root
and all 54 title pages with zero network/archive inventory:

```text
54 title pages = 53 statutory title catalogs + 1 Title 0 constitutional exclusion
```

Title 0 is `separate_constitution_scope` only when both retained official
catalogs match their exact source identity: the root URL/body
(`c945f15a4564…`, receipt `2aed70c22680…`), exact Title 0 anchor
attributes and label `THE CONSTITUTION OF THE STATE OF MONTANA`, and the
Title 0 URL/body (`ffd3643dab4e…`, receipt `545e7837b38a…`) with its
exact ordered 16-member article catalog. Any URL, digest, DOM, label,
article membership/order, disposition, or non-default configuration drift
fails closed. Constitutions remain available only through the existing
separate `constitutions` configuration and are not a dependency of the
default statutory producer.

Independent byte-level re-audit reproduced 880 known statutory chapters
with exactly five missing lettered catalogs, 4,063 retained parts with no
other known part-catalog misses, and 44,433 known leaves:

```text
44,433 known leaves
  = 14,418 typed terminals
  + 30,015 active candidates
```

Direct-only retention covers 23,363 of those active candidates:

```text
23,363 direct-retained active leaves
  +  6,652 active residuals
  = 30,015 active candidates
```

All-transport retention covers 23,366 active leaves and leaves 6,649
ordered residuals at SHA prefix `b949f71312a4`. The three additional
direct misses are §§ 39-71-2319, 39-71-2325, and 39-71-2328, whose only
retained bodies are 2016 Wayback captures; § 39-71-2324 remains
source-typed `repealed`. Those three Wayback bodies are diagnostics
unless an explicit current-equivalence proof exists for that exact URL
and byte identity.

The known request floor, before descendants of the five catalogs, is:

```text
6,657 = 5 missing chapter catalogs + 6,652 active leaves
```

The stale 35,072-row `staging-mt-v11` checkpoint remains
output-inadmissible. Do not resume that fenced root as current.

## Exact remaining URL

The exact next URL is the first known absent statutory catalog, where
the retained-replay-only traversal stopped:

```text
https://leg.mt.gov/bills/mca/title_0250/chapter_030A/parts_index.html
```

The five missing lettered chapter catalogs, in source order, are:

```text
https://leg.mt.gov/bills/mca/title_0250/chapter_030A/parts_index.html
https://leg.mt.gov/bills/mca/title_0300/chapter_002A/parts_index.html
https://leg.mt.gov/bills/mca/title_0300/chapter_004A/parts_index.html
https://leg.mt.gov/bills/mca/title_0300/chapter_009A/parts_index.html
https://leg.mt.gov/bills/mca/title_0300/chapter_012A/parts_index.html
```

Those locators are derived from official title-catalog `chapter_*A`
hrefs (`25-030A`, `30-002A`, `30-004A`, `30-009A`, `30-012A`). They are
not inferred from `OFFICIAL_TITLES`, from bounded live seed sections, or
from a guessed later `title_0990/chapter_099A` catalog.

After those five catalogs are retained, derive only their newly exposed
part and section descendants. Then submit the complete source-ordered
unique active-leaf union. The unresolved remainder after the 40,132-input
direct seed is the 6,652-URL residual at SHA
`2af9f839be756d401a45a07642d9e7fe1da00ce0bbfdae518c9ef74386450970`.
Recompute that array only from source-ordered active candidates minus
direct-retained active endpoints. A later residual SHA may be recorded
only after that derivation and must use
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## One catalog wave, then one global leaf wave

The adapter already submits each MCA dependency level as one complete
cross-parent source-ordered plural wave (`title-index`, `chapter-index`,
`part-index`, `section`). After a direct-only seed of the 40,132 verified
inputs, the unresolved remainder of `chapter-index` is the five missing
lettered catalogs. Descendants of those catalogs join `part-index` and
then `section`. Residual retries do not repeat grouped archive inventory.
Do not invent a second per-page, per-title, or CDX loop.

Required acquisition shape:

1. Seed the verified direct 40,132-input projection into a fresh absent
   evidence root (`--allowed-source-transport direct`; hardlinks,
   `copied_file_count=0`). Never overwrite v4, never mix the four
   Wayback receipts, and never resume `staging-mt-v11`.
2. Replay the retained official root and 54 title pages. Require
   `54 = 53 statutory title catalogs + 1 Title 0 constitutional
   exclusion` and fail closed on any Title 0 source-identity drift.
3. Submit the complete source-ordered chapter union as one plural batch
   named `chapter-index`. Retained replay covers the known 880-minus-5
   catalogs. The unresolved remainder is the five lettered catalogs
   above. Derive and acquire any newly exposed part/section descendants.
4. Submit the complete source-ordered unique active-leaf union as one
   plural batch named `section`. The unresolved remainder after the
   direct seed is the 6,652-URL residual named by SHA prefix
   `2af9f839be75`. Require fresh current bytes or an explicit
   current-equivalence proof for §§ 39-71-2319, 39-71-2325, and
   39-71-2328.
5. Use one `leg.mt.gov` Common Crawl inventory with URL term
   `/bills/mca/`, grouped/coalesced WARC reuse, and Wayback prefix
   inventory. Residual-only retries must not repeat grouped archive
   inventory.
6. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require first/replay frontier equality, Title 0 identity
   unchanged, and `public_law_no_state_copyright` before treating the
   pair as assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later
  `title_0990/chapter_099A` catalogs;
- treating 2016 Wayback bodies as current without an explicit
  current-equivalence proof for that exact URL and byte identity;
- Title 0 constitution-identity drift, including URL, digest, DOM,
  label, article membership/order, disposition, or non-default
  configuration changes;
- resuming fenced `staging-mt-v11` or the 35,072-row v11 checkpoint as
  current;
- per-page archive loops, per-title CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- sole-admitting `OFFICIAL_TITLES` or bounded live seed sections as the
  residual membership.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Montana binding |
|---|---|
| Source-derived frontier | Official MCA root plus title/chapter/part catalogs, then active section leaves |
| Fresh evidence generation | Seed the 40,132-input direct projection; never overwrite or mix Wayback |
| Direct-only reuse | `--allowed-source-transport direct` |
| One residual wave | unresolved remainder of `chapter-index` (5 catalogs) then `section` (6,652 leaves plus descendants) |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual wave closes:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states MT \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-mt-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-mt-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the first missing lettered chapter catalog:

```text
https://leg.mt.gov/bills/mca/title_0250/chapter_030A/parts_index.html
```

The exact remaining proof residual is those five catalogs, then the
complete 6,652-URL ordered active-leaf wave at SHA prefix `2af9f839be75`,
plus only the newly exposed descendants of the five catalogs.
