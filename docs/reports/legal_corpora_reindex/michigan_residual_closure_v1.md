# Michigan residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-101`  
Goal: `LCR-G153`  
Track: `exact51-residual-wave-d`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-101 by recording the exact remaining Michigan XML
residual: reuse the one retained v20 chapter-index root, then submit the
227 official `documents/mcl/Chapter%20N.xml` documents as one plural
media-aware wave. Host zero-network replay has not sealed a current-bundle
pair. The six closed-state steps remain the only admitted path. Hub
mutation, a static residual list, a per-page archive loop, repeating CDX
for already selected captures, importing the repaired 238-item diagnostic,
and admitting the capped 160-row corpus are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | MI |
| official domain | www.legislature.mi.gov |
| official entry | `https://www.legislature.mi.gov/Laws/ChapterIndex` |
| official_xml_locator | `https://www.legislature.mi.gov/documents/mcl/Chapter%20{N}.xml` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | official chapter-index HTML then bulk chapter XML |
| seed | one authorizing v20 root; 227 XML documents remain residual |
| retain_v20_root | true |
| resume_staging_mi_v1 | forbidden |
| resume_staging_mi_v2 | forbidden |
| resume_staging_mi_v3 | forbidden |
| import_repaired_238_diagnostic | forbidden |
| import_capped_160_row_corpus | forbidden |
| html_only_wayback_filter | forbidden |
| static_residual_list | forbidden |
| invent_later_chapter_xml_targets | forbidden |
| repeat_cdx_for_selected_captures | forbidden |
| media_aware_inventory | required |
| diagnostic_observation_at | 2026-08-26T02:33Z |
| diagnostic_live_root_bytes | 93710 |
| diagnostic_live_root_sha256_prefix | 74e42ab3a205 |
| diagnostic_live_root_authorizing | false |
| official_source_chapters | 227 |
| repaired_catalog_chapters | 238 |
| current_absent_from_repaired | 45 |
| repaired_omitted_from_current | 56 |
| chapter_number_sha256 | `8d7a03038de2065508c2d7ccb5846caf6dafaef312a5121af0e924df89036884` |
| chapter_number_sha256_prefix | 8d7a03038de2 |
| xml_url_ordered_sha256 | `5b39edd9cdd67ae513beed0ebcae3862dba3e1174aba6a788e5293610fbd5293` |
| xml_url_ordered_sha256_prefix | 5b39edd9cdd6 |
| v20_fetches | 1 |
| v20_objects | 1 |
| v20_ledgers | 0 |
| v20_frontiers | 0 |
| v20_root_bytes | 106815 |
| v20_root_sha256 | `7476e7e983fe27d4d4faf273e07b57c51f551ccb21d8517606252d39d6a53ed1` |
| v20_root_sha256_prefix | 7476e7e983fe |
| v20_receipt_sha256_prefix | 1fa879de6f4a |
| v20_source_transport | wayback |
| v20_archive_timestamp | 20240405225438 |
| retained_authorizing_inputs | 1 |
| residual_count | 227 |
| parser_input_algebra | 228 |
| residual_kind | unique ordered official chapter XML URLs after retained v20 root |
| residual_first_url | `https://www.legislature.mi.gov/documents/mcl/Chapter%201.xml` |
| residual_last_url | `https://www.legislature.mi.gov/documents/mcl/Chapter%20830.xml` |
| root_wave_name | `chapter-index` |
| residual_wave_name | `chapter-xml-1-227` |
| root_acquisition_wave_count | 1 |
| leaf_acquisition_wave_count | 1 |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| chapter_1_corpus_identity | Michigan Constitution |
| sectionless_repealed_example_chapters | 340, 804 |
| capped_160_row_jsonld_sha256_prefix | e68fbbae841d |
| repaired_diagnostic_body_sha256_prefix | ab3ca517d38d |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_ordered_sha256_prefix | 5b39edd9cdd6 |
| diagnostic_hashes_authorizing | false |
| source_bundle_prefix | a87a7e2c2a76 |

The residual SHA-256 prefix `5b39edd9cdd6` is the already published identity
of the source-ordered unique 227 official XML URLs (newline join of
`documents/mcl/Chapter%20N.xml`). Guessing the remaining hex, emitting a
227-URL dump, or inventing a later `Chapter%2056.xml` / `Chapter%20999.xml`
target fails closed: a static dump would be a forbidden residual list, and
those later chapters are not in the current 227-member catalog.

## Outcome

Michigan is **not** assembler-eligible. Chapter-index membership is known
from the retained v20 root and independently from a later live diagnostic,
the exact residual is 227 official chapter XML documents, and no XML body
is retained. No host retained-replay seal, normalized receipt,
JSON-LD/Parquet pair, or current-bundle pair exists for this observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one fresh isolated acquisition that
reuses the v20 root, submits the 227 XML URLs as one media-aware plural
wave without repeating CDX for already selected captures, then host
`--retained-replay-only` of every parser input with zero network before
materialization.

## Catalog-then-XML algebra

The Michigan Legislature publishes one official chapter index at
`https://www.legislature.mi.gov/Laws/ChapterIndex` and one bulk XML
document per numeric chapter at
`https://www.legislature.mi.gov/documents/mcl/Chapter%20N.xml`. Membership
comes from retained index bytes via `chapter_index_links`, digest-guarded
by `STRICT_CURRENT_CHAPTER_NUMBER_SHA256`. It is not the repaired 238-item
catalog-first diagnostic, not `OFFICIAL_CHAPTERS` as a sole-admitting list,
and not the capped 160-row JSON-LD.

A live official index observation at `2026-08-26T02:33Z` is 93,710 bytes
with SHA-256 prefix `74e42ab3a205`. That observation source-proves exactly
227 unique ordered numeric chapters from Chapter 1 through Chapter 830 at
chapter-number SHA `8d7a03038de2…`. Those 227 derived official XML URLs
have ordered SHA `5b39edd9cdd6…`. The live root bytes were **not** retained.

Isolated strict v2 then retained one authorizing parser input: the exact
root from Wayback capture `20240405225438`, 106,815 bytes at SHA
`7476e7e983fe…`, bound to receipt SHA `1fa879de6f4a…`, now stored as
`full-acquisition-evidence-v20-mi-v1` (one fetch, one object, no ledger,
no frontier receipt). Those bytes independently replay to the same 227
member order and pinned chapter-number digest. Strict-reusable inputs are
therefore one, and the exact residual is 227 chapter XML documents:

```text
228 parser inputs
  = 1 retained v20 chapter-index root
  + 227 official chapter XML documents
```

```text
1 retained authorizing root
  + 227 XML residuals
  = 227 remaining URL residuals
```

The current 227-member catalog has 45 identities absent from, and omits 56
identities present in, the old repaired/static 238-item diagnostic
(`catalog-first/MI` body SHA `ab3ca517d38d…`, `bundle_closed=false`). That
diagnostic cannot authorize current membership.

Chapter 1 is the Michigan Constitution. The XML normalizer preserves that
distinct corpus identity; remaining MCL statutory chapters remain
`Michigan Compiled Laws`. XML editorial notes and separately sourced
regulations are not statutes. Official chapters 340 and 804 prove the
lifecycle case where wholly repealed acts remain as statute metadata with
no section nodes: the parser types those as one and four `repealed`
terminals respectively instead of fabricating text or rejecting the
chapter. Nonrepealed sectionless acts fail closed.

Exact operative and terminal totals still require all 227 XML bodies.

## Fail-closed transport diagnostics are not a seed

Strict evidence v4 has zero fetches, objects, or ledger entries. The old
160-row JSON-LD (`e68fbbae841d…`) is capped normalized output with section
URLs but no parser-input receipts. Preserved `staging-mi-v1`,
`staging-mi-v2`, and `staging-mi-v3` are fail-closed zero-row or
incomplete-batch diagnostics and must not be resumed as current.

The v2 first-wave diagnostic used an HTML-only Wayback filter and
therefore returned zero XML inventory rows. Media-aware `staging-mi-v3`
failed closed on the first 32-XML batch: 32 verified-direct requests
missed, Common Crawl terms timed out, the legacy remote pointer fallback
returned HTTP 429, and residual-only retry recovered zero of those 32 URLs
without repeating discovery, `archive.is`, or a per-page archive loop.
V20 evidence remained exactly one fetch plus one object.

A later bounded inventory-only diagnostic over the same first 32 XML URLs
proved media-aware discovery: one logical `documents/mcl/Chapter%20`
prefix, four physical eight-target CDX queries, 32 eligible `text/xml`
rows, and 32 exact URL matches. Capture timestamps span
`20250118045847` through `20250118053823`. Media visibility is fixed.
The remaining blocker is exact capture replay/body transport; availability
for the later 195 captures is still unproved. Do not repeat CDX for
already selected exact captures inside one acquisition attempt.

## Exact remaining URL

The exact next residual URL is the first source-ordered official chapter
XML document derived from the retained v20 root:

```text
https://www.legislature.mi.gov/documents/mcl/Chapter%201.xml
```

The last source-ordered residual URL is:

```text
https://www.legislature.mi.gov/documents/mcl/Chapter%20830.xml
```

The retained catalog root is not residual. Replay it from v20:

```text
https://www.legislature.mi.gov/Laws/ChapterIndex
```

Membership is `chapter_index_links(root)` then `chapter_xml_url(number)`.
It is not `OFFICIAL_CHAPTERS`, not the 238-item repaired list, and not a
guessed later chapter number.

The exact remaining proof residual is the complete 227-URL ordered XML
difference after that retained root. Recompute that array only from the
retained catalog. A later residual SHA may be recorded only after that
derivation and must use
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.
The already published newline-joined identity remains `5b39edd9cdd6…`.

## One retained root, then one global XML wave

Required acquisition shape:

1. Seed a fresh absent evidence root. Reuse the one v20 authorizing
   chapter-index parser input. Do not import the repaired 238-item
   diagnostic, the capped 160-row JSON-LD, v4 empty ledgers, or
   `staging-mi-v1`, `staging-mi-v2`, or `staging-mi-v3`
   (`copied_file_count=0` for those forbidden trees; never overwrite a
   prior ledger).
2. Replay the retained root once as `chapter-index`. Require 227 ordered
   numeric chapters at SHA `8d7a03038de2…` (or their drifted successor),
   not the 238-row repaired list.
3. Derive official same-host XML URLs from those chapter numbers only.
   Submit the complete source-ordered unique union as one plural batch
   named `chapter-xml-1-227`.
4. Use one `www.legislature.mi.gov` Common Crawl inventory with XML-aware
   MIME terms for the XML wave and HTML-aware MIME terms for the root,
   URL terms `/documents/mcl/`, `Chapter%20`, and `.xml` on the XML wave,
   grouped/coalesced WARC reuse, and Wayback prefix inventory. Residual-only
   retries must not repeat grouped archive inventory. Do not repeat CDX
   for already selected exact captures. There is no per-page archive loop
   and no `archive.is`.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require 228 parser inputs (1 root + 227 XML, or the newly
   sealed successor), first/replay frontier equality, closed
   operative-plus-terminal algebra including sectionless repealed acts,
   preserved Chapter 1 constitution identity, and
   `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later
  `Chapter%2056.xml` / `Chapter%20999.xml` targets;
- importing the repaired 238-item diagnostic or the capped 160-row corpus;
- sole-admitting `OFFICIAL_CHAPTERS` as official membership;
- treating the live `74e42ab3a205…` diagnostic root as authorizing without
  retained bytes;
- HTML-only Wayback filters that hide `text/xml` captures;
- repeating CDX for already selected exact captures inside one attempt;
- per-page archive loops, per-chapter CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming fenced `staging-mi-v1`, `staging-mi-v2`, or `staging-mi-v3`
  as current;
- stamping historical archive XML bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Michigan binding |
|---|---|
| Source-derived frontier | Official chapter index, then 227 bulk chapter XML documents |
| Fresh evidence generation | Reuse the v20 root; never import the repaired 238-item diagnostic |
| Direct-only reuse | `--allowed-source-transport direct` for new XML bodies; v20 root is the one retained Wayback parser input |
| One residual wave | unresolved remainder of `chapter-xml-1-227`, 227 URLs |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual wave closes:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states MI \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-mi-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-mi-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the first source-ordered official chapter XML
document:

```text
https://www.legislature.mi.gov/documents/mcl/Chapter%201.xml
```

The exact remaining proof residual is the complete 227-URL ordered XML
wave after the retained v20 root, at published SHA prefix `5b39edd9cdd6`.
