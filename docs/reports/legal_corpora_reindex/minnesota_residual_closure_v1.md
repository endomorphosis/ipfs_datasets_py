# Minnesota residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-091`  
Goal: `LCR-G151`  
Track: `exact51-residual-wave-b`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-091 by recording the exact remaining Minnesota
current-edition detail residual after the verified direct-only projection.
Host zero-network replay has not sealed a current-bundle pair. The six
closed-state steps remain the only admitted path. Hub mutation, a static
residual list, a per-page archive loop, guessed later cite URLs, merging
residuals across states, and stamping 2018–2024 Wayback bodies current
are not admitted.

The earlier `minnesota_retained_frontier_audit_v1.md` remains a
read-only diagnostic. It counted 16,750 residuals because it still
treated 48 historical Wayback bodies as reusable parser inputs. This
task reseals the residual after those archive editions are excluded.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | MN |
| official domain | www.revisor.mn.gov |
| official entry | `https://www.revisor.mn.gov/statutes/` |
| official_edition | `2025 Minnesota Statutes` |
| official_section_locator | `https://www.revisor.mn.gov/statutes/cite/` |
| edition_guard | exact #header > h1 bound to 2025 Minnesota Statutes |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| seed | verified direct-only projection |
| historical_archive_edition_admission | forbidden |
| wayback_2018_2024_current_without_equivalence_proof | forbidden |
| hyphenated_citation_21853_checkpoint | output_inadmissible |
| static_residual_list | forbidden |
| guess_later_urls | forbidden |
| merge_residuals_across_states | forbidden |
| source_leaves | 54435 |
| required_detail_urls | 54383 |
| catalog_bound_renumbered_terminals | 52 |
| parser_input_frontier | 55622 |
| root_pages | 1 |
| toc_part_count | 105 |
| chapter_catalog_count | 1133 |
| direct_projection_unique_identities | 38875 |
| current_parser_inputs | 38824 |
| excluded_catalog_terminal_retained_details | 51 |
| required_retained_detail_bodies | 37585 |
| retained_operative_details | 18990 |
| retained_typed_terminal_details | 18595 |
| unclassified_retained_details | 0 |
| retained_leaf_closure | 37637 |
| wayback_historical_edition_receipts | 48 |
| residual_count | 16798 |
| residual_kind | current-edition detail URLs |
| residual_first_section | 84A.50 |
| residual_last_section | 648.51 |
| residual_first_url | `https://www.revisor.mn.gov/statutes/cite/84A.50` |
| residual_last_url | `https://www.revisor.mn.gov/statutes/cite/648.51` |
| residual_ordered_sha256 | `105c435137f5aef76b5f48662feb9aaa7ea150a5f962a82b29ad2d0032a583fd` |
| residual_ordered_sha256_prefix | `105c435137f5` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_wave_name | `section` |
| toc_part_wave_name | `toc-part` |
| catalog_wave_name | `chapter-index` |
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
| diagnostic_producer | `MinnesotaScraper@sha256:703b99e425eeae54c85e6083f079016f3bcebf323341b00344185e8fa8ce3ac6` |
| diagnostic_hashes_authorizing | false |

The residual SHA-256 `105c435137f5aef76b5f48662feb9aaa7ea150a5f962a82b29ad2d0032a583fd`
is the already published identity of the source-ordered unique 16,798-URL
current-edition detail difference. The adapter submits the complete
54,383-URL required-detail union once as `section`; retained replay covers
the 37,585 required current-edition detail bodies first, so only this
exact 16,798-URL difference is eligible for network work. This report
does not emit the 16,798 URLs: a static dump would be a forbidden
residual list and would exceed the compact-recipe admission bound.

## Outcome

Minnesota is **not** assembler-eligible. Hierarchy membership is known,
the verified direct projection is known, and the remaining leaf wave is
an exact 16,798-URL current-edition detail residual. No host
retained-replay seal, normalized receipt, JSON-LD/Parquet pair, or
current-bundle pair exists for this observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one global leaf wave against a
fresh direct-only seed of the verified projection, then host
`--retained-replay-only` with zero network before materialization.

## Direct-only current-edition algebra

The exact source-derived `2025 Minnesota Statutes` lifecycle enumerates
54,435 leaves: 54,383 required detail URLs plus 52 catalog-bound
renumbered terminals from the sealed chapter-73 catalog. Those catalog
terminals are typed from retained chapter bytes and must not be fetched
as detail pages. The complete parser-input frontier is:

```text
55,622 = 1 root + 105 TOC parts + 1,133 chapter catalogs
       + 54,383 required detail URLs
```

The direct-only retained projection has 38,875 unique request/content
identities. Its exact current parser inputs are 38,824:

```text
38,824 = 1 root + 105 TOC parts + 1,133 chapter catalogs
       + 37,585 required current-edition detail bodies
38,875 = 38,824 current parser inputs
       + 51 additional retained detail bodies whose terminal
         disposition is already source-proved by the chapter catalogs
```

Those 37,585 required details close with zero unclassified bodies:

```text
37,585 = 18,990 operative + 18,595 source-bound typed terminals
37,637 = 37,585 required retained details + 52 catalog terminals
16,798 = 54,383 required details - 37,585 retained required details
       = 54,435 source leaves - 37,637 retained leaf closure
```

All 48 previously retained Wayback inputs expose historical 2018, 2019,
2020, or 2024 statute editions. Direct-only seed skips them. They are
diagnostics unless an explicit current-equivalence proof exists for that
exact URL and byte identity. Adding those 48 historical bodies back to
the older 16,750-URL diagnostic residual recovers this 16,798-URL
current-edition residual; that identity change is not a later-URL guess.

The old 21,853-row checkpoint remains output-inadmissible because it
collapsed hyphenated citations. Do not resume it as current.

## Exact first and last residual locators

The first residual member is not an inferred next cite after a retained
section, a guessed `84A.51` continuation, the superseded diagnostic
`336.1-301` first member, or a later URL invented from `99.99`. It is
the first source-ordered required detail locator absent from the 37,585
retained current-edition detail bodies:

```text
https://www.revisor.mn.gov/statutes/cite/84A.50
```

That URL is the official Revisor cite locator for § 84A.50. The last
residual member is the same construction for the final unresolved
identity:

```text
https://www.revisor.mn.gov/statutes/cite/648.51
```

A later residual SHA may be recomputed only from the source-ordered
unique required-detail array after a current-edition catalog replay
minus those 37,585 retained endpoints. It must still start with
`105c435137f5` or record a newly hashed equal count from a drifted
official catalog. Guessing the remaining hex, inventing `84A.51` or
`99.99`, substituting a static URL list, or restoring the 16,750-URL
diagnostic as current fails closed.

## One global residual wave

Root, TOC-part, and chapter discovery remain three dependency-ordered
waves because each level supplies the next level's exact identities.
The adapter already submits the complete cross-chapter required-detail
union once as `section`. Parsing and the bounded checkpoint slice must
not fragment transport into separate archive request waves.

Required acquisition shape:

1. Seed the verified direct projection into a fresh absent evidence
   root (`--allowed-source-transport direct`; hardlinks,
   `copied_file_count=0`). Never mix the 48 historical Wayback receipts
   and never resume the 21,853-row hyphenated checkpoint.
2. Replay the retained official root, 105 TOC parts, and 1,133 chapter
   catalogs from that ledger. Require
   `55,622 = 1 + 105 + 1,133 + 54,383` after the residual wave, with
   every parser input bound to exact `#header > h1` text
   `2025 Minnesota Statutes`.
3. Submit the complete source-ordered 54,383 required-detail union as
   one plural batch named `section`. Retained replay covers 37,585
   current-edition detail inputs. The unresolved remainder is the
   16,798-URL residual.
4. Use one `www.revisor.mn.gov` Common Crawl inventory with URL term
   `/statutes/`, grouped/coalesced WARC reuse, and Wayback prefix
   inventory. Residual-only retries must not repeat grouped archive
   inventory. Reject any 2018, 2019, 2020, or 2024 archive body rather
   than stamping it current.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require first/replay frontier equality, closed
   operative/terminal algebra over the 54,435 source leaves, the pinned
   2025 edition, and `public_law_no_state_copyright` before treating
   the pair as assembler-eligible evidence.

Forbidden:

- static residual URL lists or sample caps;
- guessed later `/statutes/cite/` URLs, including `84A.51` and `99.99`;
- merging Minnesota residuals with Missouri, Washington, or any other
  jurisdiction residual;
- per-page archive loops and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming the 21,853-row hyphenated checkpoint as current;
- stamping 2018–2024 Wayback bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Minnesota binding |
|---|---|
| Source-derived frontier | Official 2025 Revisor root TOC-part order plus chapter-catalog required-detail identities |
| Fresh evidence generation | Seed the verified direct projection; never mix historical Wayback editions |
| Direct-only reuse | `--allowed-source-transport direct` |
| One residual wave | unresolved remainder of `section`, 16,798 URLs |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |
| Edition guard | exact `#header > h1` `2025 Minnesota Statutes` on root, TOC, chapter, detail, replay, and closure |

Host replay command shape after the residual wave closes:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states MN \
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
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-mn-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-mn-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the first residual member:

```text
https://www.revisor.mn.gov/statutes/cite/84A.50
```

The exact remaining proof residual is the complete 16,798-URL ordered
current-edition detail wave from that locator through
`https://www.revisor.mn.gov/statutes/cite/648.51` at SHA
`105c435137f5aef76b5f48662feb9aaa7ea150a5f962a82b29ad2d0032a583fd`.
