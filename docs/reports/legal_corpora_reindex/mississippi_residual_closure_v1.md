# Mississippi residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-102`  
Goal: `LCR-G153`  
Track: `exact51-residual-wave-d`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-102 by recording the exact remaining Mississippi
delegated Lexis residual: retain the Legislature delegation, publisher
redirect, container root, and 51 TOC byte strings first, then submit the
30,291 current bodies. Host zero-network replay has not sealed a
current-bundle pair. The six closed-state steps remain the only admitted
path. Hub mutation, a static residual list, a per-page archive loop,
invented even-numbered titles, and the dead 2024 bill-status path are
not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | MS |
| authority_domain | www.legislature.ms.gov |
| publisher_domain | www.lexisnexis.com |
| container_domain | advance.lexis.com |
| official entry | `https://www.legislature.ms.gov/` |
| official_help_url | `https://www.legislature.ms.gov/help/` |
| official_secretary_of_state_url | `https://www.sos.ms.gov/publications-external-affairs/mississippi-law` |
| publisher_entry | `http://www.lexisnexis.com/hottopics/mscode/` |
| container_url | `https://advance.lexis.com/container?config=00JAAzNzhjOTYxNC0wZjRkLTQzNzAtYjJlYS1jNjExZWYxZGFhMGYKAFBvZENhdGFsb2cMlW40w5iIH7toHnTBIEP0` |
| toc_endpoint | `https://advance.lexis.com/r/tocprovider/6gf5kkk/toc/6gf5kkk` |
| toc_root | `6gf5kkk` |
| root_membership | AAB recent-legislation plus odd Titles 1–99 (`AAC`–`ABZ`) |
| even_numbered_titles | forbidden |
| dead_2024_billstatus_path | forbidden |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| seed | fresh isolated acquisition; zero authorizing retained inputs |
| catalog_first_repaired_99_titles | forbidden |
| unicourt_r78_secondary_cache | forbidden |
| justia_singleton_secondary_cache | forbidden |
| patch_archive_substitution | forbidden |
| static_residual_list | forbidden |
| invent_even_titles | forbidden |
| parser | Mississippi-specific delegated Lexis catalog then current bodies |
| same_target_parser_for_live_and_replay | true |
| retain_legislature_publisher_container_and_51_toc_bytes_first | true |
| fetch_catalog_before_bodies | true |
| strict_reusable_input_count | 0 |
| diagnostic_observation_at | 2026-08-26T01:33:48.867054+00:00 |
| root_nodes | 51 |
| title_roots | 50 |
| recent_legislation_roots | 1 |
| complete_open_to_responses | 51 |
| descendant_nodes | 33600 |
| all_nodes_including_roots | 33651 |
| document_like_nodes | 30432 |
| current_section_candidates | 30270 |
| current_section_collection_candidates | 3 |
| untyped_current_document_residuals | 3 |
| recent_legislation_locators | 15 |
| future_effectiveness_locators | 80 |
| future_structural_placeholders | 2 |
| publisher_editorial_structural_documents | 59 |
| catalog_exclusions | 141 |
| unique_main_section_identities | 30172 |
| repeated_section_identities | 158 |
| extra_variant_locators | 177 |
| state_delegation_gets | 1 |
| publisher_entry_gets | 1 |
| rendered_root_gets | 1 |
| toc_patch_inputs | 51 |
| authority_catalog_residual_count | 54 |
| body_residual_count | 30291 |
| residual_count | 30345 |
| residual_kind | delegated Lexis catalog then 30,291 current bodies |
| residual_first_url | `https://www.legislature.ms.gov/` |
| residual_wave_name | `source-ordered-current-bodies` |
| toc_patch_wave_name | `51-root-open-to` |
| ordered_request_wave_counts | 1,1,1,51,30291 |
| get_authority_wave_count | 3 |
| toc_patch_wave_count | 1 |
| body_get_wave_count | 1 |
| catalog_acquisition_wave_count | 1 |
| leaf_acquisition_wave_count | 1 |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | GET URLs: `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`; PATCH identities bind method plus request-body SHA-256 |
| residual_ordered_sha256_prefix | source_derived_after_retained_catalog |
| diagnostic_root_rendered_sha256 | `69710a43c4c9f0f37606e8aed41a1e4bc9c3e5ec8bf1b1c7baa664bffc3d2da7` |
| diagnostic_51_response_manifest_sha256 | `7e84b255f0806dd18af7cba3a3ea8a2b06049ff025393c110d431859af85fc88` |
| diagnostic_root_semantic_sha256 | `f5b4d0126272bd114e50a92f7dee937b543cb4ccb1181f73d6dc033f14849e69` |
| diagnostic_all_node_semantic_sha256 | `85bff81bbb5b3af648dabbb0832e6d5af108ea4079d806b91b6bc1be3fb6660c` |
| diagnostic_main_document_semantic_sha256 | `cfa917901e8e03f35986047051e4877a07ea5b3972afae54a9f81e03a2adfea3` |
| diagnostic_hashes_authorizing | false |
| diagnostic_producer | `MississippiScraper@sha256:47adb7288b80a3e7bc9cff8994ce19a9fdfb0b8b174cf1790fa044bf413b6080` |

The residual SHA-256 prefix `source_derived_after_retained_catalog` is the
canonical JSON digest of the source-ordered 30,291 current-body URLs after
a retained Legislature/publisher/container/51-TOC catalog. It is not a
predeclared hex prefix and does not authorize those bytes. This report
does not emit the 30,291 body URLs or the 51 PATCH request bodies: a
static dump would be a forbidden residual list and would exceed the
compact-recipe admission bound. The 30,345-input residual is mixed GET
plus PATCH identities, so a URL-only digest of 30,345 locators would
erase the TOC request-body contract.

The in-memory diagnostic hashes above, and the independent adapter
projection hashes recorded in `mississippi_lexis.py`, are not
authorizing. Raw rendered-root and TOC JSON contain session-local
fields and changed hash across diagnostic runs. A future authorizing
run must retain every exact raw response while separately binding the
stable semantic membership.

## Outcome

Mississippi is **not** assembler-eligible. Delegated hierarchy membership
is known from a metadata-only `2026-08-26T01:33:48Z` observation.
Strict-reusable current-source parser inputs are exactly zero. No host
retained-replay seal, normalized receipt, JSON-LD/Parquet pair, or
current-bundle pair exists for this observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one fresh isolated acquisition
of the 54 authority/catalog identities plus the 30,291 source-derived
bodies, then host `--retained-replay-only` of all 30,345 parser inputs
with zero network before materialization.

## Delegated Lexis residual algebra

The Mississippi Legislature home and help pages, independently
corroborated by the Secretary of State's Mississippi Law page, delegate
the public unannotated Code to the publisher entry, which redirects to
the exact free-public-access container. The rendered root contains
exactly 51 source roots: `AAB` recent-legislation plus Titles 1 through
99, odd numbers only (`AAC`–`ABZ`). Even-numbered titles are not Code
roots. `Volume` tables, the Constitution, administrative rules, court
rules, session bills, and bill histories are outside this Code-body
frontier.

One PATCH at each root's maximum advertised `open-to` level returns that
root's complete hierarchy. The exact catalog request set is therefore 51
source-native PATCH identities, not thousands of node-by-node
expansions.

```text
54 authority/catalog inputs
  = 1 Legislature GET
  + 1 publisher-entry GET
  + 1 rendered-container GET
  + 51 deepest TOC PATCH identities

30,291 current body residuals
  = 30,270 individually labeled current section candidates
  + 3 current multi-section collection candidates
  + 3 untyped current document locators
  + 15 recent-legislation locators

30,345 exact residual parser inputs
  = 54 authority/catalog
  + 30,291 bodies
```

The following 141 document-like nodes are typed catalog exclusions and
are not body-acquisition targets for the current Code:

```text
141 catalog exclusions
  = 80 full future-effectiveness locators
  + 2 bare future structural placeholders
  + 59 publisher/editorial structural documents

30,291 residual body requests + 141 catalog exclusions = 30,432 document-like nodes
```

Structural membership from the diagnostic observation closes as:

```text
33,651 nodes = 51 roots + 33,600 descendants
30,432 document-like nodes among those descendants
```

Repeated current citation variants (158 identities, 177 extra locators)
are fetched as distinct URNs and reconciled only after exact-body
parsing. No variant is silently deduplicated by citation alone. Recent
legislation locators remain body targets until their bodies establish
enacted section identity. Catalog terminals, untyped locators, and
collections stay body targets until the document parser confirms them.

Those hashes and counts are drift sentinels. They do not replace raw
transport receipts.

## Exact remaining URL

The exact next URL is the first source-ordered residual member, because
zero current-source parser inputs are retained:

```text
https://www.legislature.ms.gov/
```

That locator must prove the Lexis Mississippi Code delegation. The next
GET identities are the publisher entry
`http://www.lexisnexis.com/hottopics/mscode/` and the exact container.
The 51 TOC identities then reuse
`https://advance.lexis.com/r/tocprovider/6gf5kkk/toc/6gf5kkk` with
distinct PATCH request bodies bound to each root's maximum advertised
`open-to` level. Body URLs are derived only from retained (or freshly
acquired) catalog content-item paths under
`/shared/document/statutes-legislation/urn:contentItem:…`.

Invented even-numbered titles, descendants of the dead
`https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/`
path, a GET archive of the TOC endpoint, and any static 30,291-URL dump
fail closed.

The exact remaining proof residual is the complete 30,345-input ordered
frontier. Recompute GET membership only from the three
authority/catalog GET URLs plus source-derived current document paths.
Recompute PATCH membership only from `toc_open_to_request` after the
rendered root closes. A later residual SHA for the 30,291 paths must
use
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`
and is recorded only after that derivation.

## Five ordered residual waves

Required acquisition shape:

1. Do not seed the catalog-first repaired 99-title body (even titles and
   the dead 2024 path), the 1997 bill-history snapshot, UniCourt `r78`,
   the Justia § 97-3-7 singleton, or `/legislation/` landing-page
   bytes as authorizing Code membership. Start a fresh absent evidence
   root. Direct-only reuse applies only after an authorizing GET is
   retained (`--allowed-source-transport direct`; hardlinks,
   `copied_file_count=0`).
2. Acquire the Legislature GET, publisher-entry GET, and exact
   container GET as three source-ordered authority waves. Each GET wave
   uses the shared plural path: one Common Crawl inventory per domain
   per wave, grouped/coalesced WARC reuse, Wayback prefix inventory,
   residual-only retries, and no per-page archive loop. The Secretary
   of State page may be retained as corroboration; it is not a
   substitute for the Legislature-to-container chain.
3. Replay or acquire the 51 deepest TOC PATCH identities as one ledger
   wave named `51-root-open-to`. A GET archive cannot prove a PATCH
   request body. `patch_archive_substitution` remains forbidden.
   Require the same or a newly sealed `AAB` plus odd Titles 1–99
   membership, 30,291 current bodies, and 141 catalog exclusions (or
   their drifted successor algebra).
4. Derive the 30,291 current document URLs from that catalog and submit
   them as one same-domain plural GET wave named
   `source-ordered-current-bodies` on `advance.lexis.com`. Future,
   placeholder, and editorial nodes stay typed exclusions. Repeated
   citations stay distinct content-item rows until source-bound
   temporal evidence selects or preserves the current variant.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require ordered wave counts `1,1,1,51,30291`, first/replay
   frontier equality, and `public_law_no_state_copyright` before treating
   the pair as assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented even-numbered
  titles (`Title 2` … `Title 98`) and later `title-99` hunts;
- targeting
  `https://billstatus.ls.state.ms.us/documents/2024/html/code_sections/`
  or its 2025/2026 counterparts as a current Code root;
- importing the catalog-first repaired JSON (`body.bin` SHA
  `b14bc30cb959…`), the 99-row frontier, UniCourt `r78` (`2fe4efee85be…`),
  or the Justia singleton as authorizing evidence;
- PATCH archive substitution, GET-to-PATCH identity collapse, and
  node-by-node TOC loops;
- per-page archive loops, per-title CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming a fenced staging root as current;
- stamping historical archive bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity;
- treating the in-memory diagnostic hashes as authorizing without
  retained Legislature, publisher, container, and 51 TOC bytes.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Mississippi binding |
|---|---|
| Source-derived frontier | Legislature Lexis delegation, exact container, 51 PATCH TOCs, 30,291 current bodies |
| Fresh evidence generation | Fresh isolated acquisition; never seed even titles or the dead 2024 path |
| Direct-only reuse | `--allowed-source-transport direct` after an authorizing GET is retained |
| One residual wave | five ordered waves `1,1,1,51,30291`; GET remainder uses grouped `advance.lexis.com` body contract |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual waves close:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states MS \
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
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-ms-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-ms-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

Fresh isolated acquisition, before any authorizing GET exists, remains the
strict full-corpus command in `mississippi_current_source_resolution_v1.md`.
It must stop at the delegated-body-frontier blocker until the 30,345
identities are retained.

## Next residual URL

The exact next URL is:

```text
https://www.legislature.ms.gov/
```

The exact remaining proof residual is the complete 30,345-input ordered
delegated Lexis frontier: 1 + 1 + 1 + 51 PATCH + 30,291 bodies. The body
residual SHA prefix remains `source_derived_after_retained_catalog`.
