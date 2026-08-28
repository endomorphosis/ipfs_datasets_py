# Tennessee residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-104`  
Goal: `LCR-G153`  
Track: `exact51-residual-wave-d`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-104 by recording the exact remaining Tennessee
delegated Lexis residual: 36,118 parser inputs after a metadata-only
observation that retained zero authorizing current-source bytes. Host
zero-network replay has not sealed a current-bundle pair. The six
closed-state steps remain the only admitted path. Hub mutation, a static
residual list, a per-page archive loop, PATCH archive substitution, the
synthetic v4 receipt, and secondary caches are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | TN |
| authority_domain | wapp.capitol.tn.gov |
| publisher_domain | www.lexisnexis.com |
| container_domain | advance.lexis.com |
| official entry | `https://wapp.capitol.tn.gov/apps/WebPublications/` |
| publisher_entry | `https://www.lexisnexis.com/hottopics/tncode` |
| container_url | `https://advance.lexis.com/container?config=014CJAA5ZGVhZjA3NS02MmMzLTRlZWQtOGJjNC00YzQ1MmZlNzc2YWYKAFBvZENhdGFsb2e9zYpNUjTRaIWVfyrur9ud` |
| toc_endpoint | `https://advance.lexis.com/r/tocprovider/6gf5kkk/toc/6gf5kkk` |
| toc_root | `6gf5kkk` |
| excluded_root | Volume 13 Tables |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| seed | fresh isolated acquisition; zero authorizing retained inputs |
| synthetic_v4_receipt | forbidden |
| secondary_caches | forbidden |
| patch_archive_substitution | forbidden |
| static_residual_list | forbidden |
| dead_tn_gov_locators | forbidden |
| parser | Tennessee-specific strict Lexis parser |
| same_target_parser_for_live_and_replay | true |
| strict_reusable_input_count | 0 |
| statutory_title_roots | 71 |
| expandable_title_roots | 69 |
| direct_reserved_title_roots | 2 |
| source_roots_including_tables | 72 |
| descendant_nodes | 40193 |
| descendant_containers | 4149 |
| descendant_document_leaves | 36044 |
| document_leaves | 36046 |
| catalog_terminal_count | 1359 |
| catalog_repealed | 720 |
| catalog_reserved | 561 |
| catalog_transferred | 53 |
| catalog_expired | 16 |
| catalog_obsolete | 9 |
| body_unclassified_candidates | 34687 |
| repeated_citation_identity_count | 182 |
| state_delegation_gets | 1 |
| publisher_entry_gets | 1 |
| rendered_root_gets | 1 |
| toc_patch_inputs | 69 |
| authority_catalog_residual_count | 72 |
| body_residual_count | 36046 |
| residual_count | 36118 |
| residual_kind | delegated Lexis frontier of 36,118 parser inputs |
| residual_first_url | `https://wapp.capitol.tn.gov/apps/WebPublications/` |
| residual_wave_name | `document body wave` |
| toc_patch_wave_name | `deepest title TOC wave` |
| ordered_request_wave_counts | 1,1,1,69,36046 |
| get_authority_wave_count | 3 |
| toc_patch_wave_count | 1 |
| body_get_wave_count | 1 |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | GET URLs: `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`; PATCH identities bind method plus request-body SHA-256 |
| residual_ordered_sha256_prefix | `af6b3962a8ee` |
| ordered_content_path_sha256 | `af6b3962a8eedc12d5f76d98608deee37c8398b30236829b504986c42234599b` |
| title_root_membership_sha256 | `88135a531583ec0784f72ab7ec436e282f61da93df58e0c86b98f65983620566` |
| document_membership_sha256 | `8bfc62cda73e7529b30f5848d7cb9128c341d6c0f8910c6ed08dc0beb58d7286` |
| diagnostic_producer | `TennesseeScraper@sha256:42e4c260c2be4599bd2acccf4763d6d907c2f214cc764770f3c3c0e8bc4b5528` |

The residual SHA-256 prefix `af6b3962a8ee` is the already published
diagnostic identity of the source-ordered 36,046 document content-item
paths. It does not authorize those bytes. This report does not emit the
36,046 body URLs or the 69 PATCH request bodies: a static dump would be a
forbidden residual list and would exceed the compact-recipe admission
bound. The 36,118-input residual is mixed GET plus PATCH identities, so a
URL-only digest of 36,118 locators would erase the TOC request-body
contract.

## Outcome

Tennessee is **not** assembler-eligible. Delegated hierarchy membership is
known from a metadata-only observation. Strict-reusable current-source
parser inputs are exactly zero. No host retained-replay seal, normalized
receipt, JSON-LD/Parquet pair, or current-bundle pair exists for this
observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one fresh isolated acquisition of
the 72 authority/catalog identities plus the 36,046 source-derived bodies,
then host `--retained-replay-only` of all 36,118 parser inputs with zero
network before materialization.

## Delegated Lexis residual algebra

The General Assembly Web Publications page delegates `Tennessee Code` to
the publisher entry, which redirects to the exact free-public-access
container. Titles 1 through 71 are the statutory roots; `Volume 13 Tables`
is excluded. Titles 19 and 51 are direct reserved-document roots. The
other 69 titles expand by one deepest-level `open-to` PATCH each, not a
node-by-node request loop.

```text
72 authority/catalog inputs
  = 1 General Assembly GET
  + 1 publisher-entry GET
  + 1 rendered-container GET
  + 69 deepest TOC PATCH identities

36,046 document leaves
  = 36,044 descendant documents
  + 2 direct reserved roots

36,118 exact residual parser inputs
  = 72 authority/catalog
  + 36,046 bodies
```

Catalog labels partition those leaves as 1,359 explicit terminals plus
34,687 body-unclassified candidates. That label partition is not final
body algebra. All 36,046 content-item paths remain body targets until a
retained document proves a catalog terminal without silently discarding
reserved, transferred, expired, obsolete, or repeated variants. Exactly
182 citation identities repeat across distinct content-item paths and must
not be deduplicated before source-bound temporal reconciliation.

Structural membership from the diagnostic observation closes as:

```text
40,193 descendants = 4,149 containers + 36,044 document leaves
40,264 statutory nodes = 69 expandable roots + 4,149 containers
                         + 36,046 document leaves
```

Those hashes and counts are drift sentinels. They do not replace raw
transport receipts.

## Exact remaining URL

The exact next URL is the first source-ordered residual member, because
zero current-source parser inputs are retained:

```text
https://wapp.capitol.tn.gov/apps/WebPublications/
```

That locator must prove the Lexis `Tennessee Code` delegation. The next
GET identities are the publisher entry and the exact container. The 69
TOC identities then reuse `https://advance.lexis.com/r/tocprovider/6gf5kkk/toc/6gf5kkk`
with distinct PATCH request bodies bound to each expandable title's
maximum advertised `open-to` level. Body URLs are derived only from
retained (or freshly acquired) catalog content-item paths under
`/shared/document/statutes-legislation/urn:contentItem:…`.

Invented descendants of the dead `https://www.tn.gov/tga/statutes.html`
entry, a GET archive of the TOC endpoint, and any static 36,046-URL dump
fail closed.

The exact remaining proof residual is the complete 36,118-input ordered
frontier. Recompute GET membership only from the three authority/catalog
GET URLs plus source-derived document paths. Recompute PATCH membership
only from `canonical_toc_patch_request` after the rendered root closes.
A later residual SHA for the 36,046 paths must still start with
`af6b3962a8ee` or record a newly hashed equal count from a drifted
official catalog.

## Five ordered residual waves

Required acquisition shape:

1. Do not seed the synthetic v4 receipt, Justia/Jina caches, Hugging Face
   blobs, or the dead `tn.gov` catalog. Start a fresh absent evidence
   root. Direct-only reuse applies only after an authorizing GET is
   retained (`--allowed-source-transport direct`; hardlinks,
   `copied_file_count=0`).
2. Acquire the General Assembly GET, publisher-entry GET, and exact
   container GET as three source-ordered authority waves. Each GET wave
   uses `_fetch_tennessee_lexis_get_wave` / the shared plural path: one
   Common Crawl inventory per domain per wave, grouped/coalesced WARC
   reuse, Wayback prefix inventory, residual-only retries, and no
   per-page archive loop.
3. Replay or acquire the 69 deepest TOC PATCH identities as one ledger
   wave named `deepest title TOC wave`. A GET archive cannot prove a
   PATCH request body. `toc_patch_archive_substitution_allowed` remains
   false.
4. Derive the 36,046 document URLs from that catalog and submit them as
   one same-domain plural GET wave named `document body wave`. Catalog
   terminals stay body targets until the document parser confirms them.
   Repeated citations stay distinct content-item rows until source-bound
   temporal evidence selects or preserves the current variant.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require ordered wave counts `1,1,1,69,36046`, first/replay
   frontier equality, and `public_law_no_state_copyright` before treating
   the pair as assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented `tn.gov` title
  locators;
- PATCH archive substitution, GET-to-PATCH identity collapse, and
  node-by-node TOC loops;
- per-page archive loops, per-title CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming a fenced staging root as current;
- stamping historical archive bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity;
- using the synthetic v4 receipt (`response.bin` SHA
  `89e20a95d9fd…`, frontier digest `6850ed433c01…`) or secondary
  Justia/Jina/Hugging Face caches as authorizing evidence.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Tennessee binding |
|---|---|
| Source-derived frontier | General Assembly Lexis delegation, exact container, 69 PATCH TOCs, 36,046 content-item bodies |
| Fresh evidence generation | Fresh isolated acquisition; never seed synthetic v4 or secondary caches |
| Direct-only reuse | `--allowed-source-transport direct` after an authorizing GET is retained |
| One residual wave | five ordered waves `1,1,1,69,36046`; GET remainder uses `_fetch_tennessee_lexis_get_wave` |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual waves close:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states TN \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-tn-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-tn-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

Fresh isolated acquisition, before any authorizing GET exists, remains the
strict full-corpus command in `tennessee_current_source_resolution_v1.md`.
It must stop at the delegated-frontier blocker until the 36,118 identities
are retained.

## Next residual URL

The exact next URL is:

```text
https://wapp.capitol.tn.gov/apps/WebPublications/
```

The exact remaining proof residual is the complete 36,118-input ordered
delegated Lexis frontier: 1 + 1 + 1 + 69 PATCH + 36,046 bodies. The
published diagnostic path SHA prefix remains `af6b3962a8ee`.
