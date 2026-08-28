# Rhode Island residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-095`  
Goal: `LCR-G152`  
Track: `exact51-residual-wave-c`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-095 by recording the exact remaining Rhode Island
nested-catalog residual, then the source-ordered leaf union. Host
zero-network replay has not sealed a current-bundle pair. The six
closed-state steps remain the only admitted path. Hub mutation, a static
residual list, a per-page archive loop, a per-slice archive inventory, and
resuming zero-row `staging-ri-v1` through `staging-ri-v3` as current are
not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | RI |
| official domain | webserver.rilegislature.gov |
| official entry | `https://webserver.rilegislature.gov/Statutes/` |
| scraper_official_entry_url | `https://webserver.rilegislature.gov/Statutes/TITLE1/INDEX.HTM` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| seed | 3018 unique direct inputs |
| resume_zero_row_staging_ri_v1_v3 | forbidden |
| static_residual_list | forbidden |
| per_slice_archive_inventory | forbidden |
| unique_direct_inputs | 3018 |
| root_catalogs | 1 |
| title_catalogs | 49 |
| chapter_catalogs | 2817 |
| part_catalogs | 151 |
| retained_bytes | 13860568 |
| direct_section_chapters | 2788 |
| part_index_chapters | 23 |
| typed_terminal_chapters | 6 |
| direct_section_parts | 142 |
| nested_index_parents | 9 |
| known_section_identities | 34184 |
| temporal_locators | 69 |
| source_bound_chapter_range_materials | 2 |
| residual_count | 29 |
| residual_kind | unique ordered nested catalogs then leaf union |
| residual_first_url | first source-ordered unique nested catalog derived from the nine nested-index parents after the 3,018-input seed |
| residual_wave_name | `subpart-index` |
| leaf_union_wave_name | `sections` |
| nested_catalog_wave_count | 1 |
| leaf_union_wave_count | 1 |
| fetch_nested_catalogs_before_leaf_union | true |
| known_leaves | 34184 |
| leaf_union_count | source_dependent_after_29_nested_catalogs |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_ordered_sha256_prefix | aeb95ffc2041 |
| source_bundle_prefix | `daefc41326a0` |

The residual SHA-256 prefix `aeb95ffc2041` is the already published identity
of the source-ordered unique nested-catalog URL array. Recompute that digest
only from nested locators derived from the nine nested-index parents. This
report does not emit the 29 URLs: a static dump would be a forbidden residual
list and would exceed the compact-recipe admission bound. The later leaf-union
count remains source-dependent on those 29 catalogs and is therefore not a
predeclared integer.

## Outcome

Rhode Island is **not** assembler-eligible. Hierarchy membership is known
through the 3,018 unique direct inputs, nested-index parents are known, and
the remaining first residual is an exact 29-URL nested-catalog wave. No host
retained-replay seal, normalized receipt, JSON-LD/Parquet pair, or
current-bundle pair exists for this observation.

The allowed stopping point for this child task is the typed residual below.
The remaining operator action is to fetch the 29 nested catalogs first
against a fresh direct-only seed of the 3,018 unique inputs, derive only the
newly exposed descendants, submit the complete source-ordered leaf union
once, then host `--retained-replay-only` with zero network before
materialization.

## Nested-catalog then leaf algebra

Strict lifecycle derives the 3,018 unique direct inputs from the official
`/Statutes/` root, not from `OFFICIAL_TITLES` as membership, a repaired
catalog, or any other static URL list:

```text
3,018 = 1 root + 49 title catalogs + 2,817 chapter catalogs + 151 part catalogs
```

Those bindings close over 13,860,568 bytes with zero missing, duplicate,
unused, unsafe, or nonauthorizing inputs. Source derivation of the retained
chapter and part catalogs is:

```text
2,817 chapters = 2,788 direct-section + 23 part-index + 6 typed terminals
151 parts     = 142 direct-section + 9 nested-index parents
```

The nine nested-index parents are the only retained intermediates that
expose a further catalog level. Their source-ordered unique children are
exactly 29 nested catalogs. Known leaf membership already visible without
those 29 catalogs is 34,184 unique section identities, plus 69 temporal
locators and two source-bound chapter-range materials. Typed terminal
chapters are not leaf residuals.

Retained-vs-residual algebra is therefore:

```text
3,018 unique direct inputs
  + 29 nested catalogs
  + 34,184 known leaves
  + only descendants newly exposed by the 29 catalogs
```

The first residual is the 29-catalog difference. The second residual is the
complete source-ordered leaf union after those catalogs close. Guessing a
later nested `INDEX.htm`, emitting a 29-URL dump, or submitting leaves
before nested catalogs fails closed.

## Exact remaining URL

The exact next URL is the first source-ordered unique nested catalog derived
from the nine nested-index parents after a 3,018-input seed. That locator is
built only from a retained parent catalog that the nested-index parser
admits. It is not inferred from `OFFICIAL_TITLES`, from a bounded live
sample, or from a guessed Title/Chapter/Part path.

The exact remaining proof residual is the complete 29-URL ordered nested
catalog wave at SHA prefix `aeb95ffc2041`, then the complete source-ordered
leaf union of the 34,184 known leaves plus only descendants newly exposed by
those 29 catalogs. Recompute the nested-catalog array only from parent
catalog replay. A later nested-catalog SHA may be recorded only after that
derivation and must use
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## Nested catalogs first, then one leaf union

The adapter already reconstructs the official tree as ordered plural waves:
root, titles, chapters, parts, nested catalogs (`subpart-index`), then the
complete section union (`sections`). After a direct-only seed of the 3,018
unique inputs, the unresolved nested remainder is the exact 29-catalog
residual. Nested catalogs must close before any leaf union is submitted.
Residual retries do not repeat grouped archive inventory. Do not invent a
second per-title, per-chapter, per-part, or CDX loop.

Required acquisition shape:

1. Seed verified direct 3,018 inputs into a fresh absent evidence root
   (`--allowed-source-transport direct`; hardlinks, `copied_file_count=0`).
   Do not resume zero-row `staging-ri-v1`, `staging-ri-v2`, or
   `staging-ri-v3` as current.
2. Replay the retained root, 49 titles, 2,817 chapters, and 151 parts from
   that ledger. Require nine nested-index parents and no mixed
   direct-section/part-index chapter.
3. Submit the 29 source-ordered unique nested catalogs as one plural batch
   named `subpart-index`. Do not open one inventory or HTTP client per
   parent, title, or slice.
4. Derive additional leaves only from those 29 catalogs. Submit the
   complete source-ordered leaf union (34,184 known leaves plus only newly
   exposed descendants) as one plural batch named `sections`.
5. Use one `webserver.rilegislature.gov` Common Crawl inventory with URL
   term `/Statutes/`, grouped/coalesced WARC reuse, and Wayback prefix
   inventory. Residual-only retries must not repeat grouped archive
   inventory.
6. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require first/replay frontier equality and
   `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later nested
  `INDEX.htm` targets;
- per-page archive loops, per-slice Common Crawl/CDX inventory, and
  `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming a fenced or zero-row staging root as current, including
  `staging-ri-v1` through `staging-ri-v3`;
- stamping historical archive bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity;
- submitting the leaf union before the 29 nested catalogs close.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Rhode Island binding |
|---|---|
| Source-derived frontier | Official `/Statutes/` root, titles, chapters, parts, then nested catalogs |
| Fresh evidence generation | Seed 3,018 unique direct inputs; never overwrite or promote v1–v3 |
| Direct-only reuse | `--allowed-source-transport direct` |
| Nested-catalog residual | `subpart-index`, 29 URLs, SHA prefix `aeb95ffc2041` |
| Leaf union | unresolved remainder of `sections` after nested catalogs close |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual waves close:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states RI \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-ri-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-ri-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the first source-ordered unique nested catalog derived
from the nine nested-index parents after the 3,018-input seed. Inventing a
later nested `INDEX.htm` that is not in that 29-URL difference fails closed.

The exact remaining proof residual is the complete 29-URL ordered nested
catalog wave at SHA prefix `aeb95ffc2041`, then the complete source-ordered
leaf union whose final count remains source-dependent on those 29 catalogs.
