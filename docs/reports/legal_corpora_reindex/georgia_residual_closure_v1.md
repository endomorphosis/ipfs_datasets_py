# Georgia residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-100`  
Goal: `LCR-G153`  
Track: `exact51-residual-wave-d`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-100 by recording the exact remaining Georgia residual:
retain the delegated catalog (root plus 53 title-patch byte strings) first,
then submit the 29,165 current official section body URLs. Host
zero-network replay has not sealed a current-bundle pair. The six
closed-state steps remain the only admitted path. Hub mutation, a static
residual list, a per-page archive loop, legislative-summary PDFs, and the
two-row artifact are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | GA |
| official domain | www.legis.ga.gov |
| official entry | `https://www.legis.ga.gov/legislation/georgia-code` |
| official_delegated_entry | `https://www.lexisnexis.com/hottopics/gacode/` |
| official_container | `https://advance.lexis.com/container?config=00JAAzZDgzNzU2ZC05MDA0LTRmMDItYjkzMS0xOGY3MjE3OWNlODIKAFBvZENhdGFsb2fcIFfJnJ2IC8XZi1AYM4Ne` |
| official_body_locator | `https://www.legis.ga.gov/legislation/georgia-code/title-{title}/chapter-{chapter}/section-{section}` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | delegated Lexis TOC then official legis.ga.gov bodies |
| retain_root_and_title_patch_bytes_first | true |
| fetch_catalog_before_bodies | true |
| import_legislative_summary_pdfs | forbidden |
| import_two_row_artifact | forbidden |
| static_residual_list | forbidden |
| invent_later_section_targets | forbidden |
| diagnostic_observation_at | 2026-08-26T00:34:55Z |
| catalog_titles | 53 |
| catalog_nodes | 36120 |
| catalog_expandable_nodes | 3970 |
| catalog_root_gets | 1 |
| catalog_title_patches | 53 |
| catalog_inputs | 54 |
| catalog_bytes_retained | 0 |
| temporal_section_locators | 29358 |
| current_identities | 29165 |
| temporal_exclusions | 193 |
| expected_operative_bodies | 28417 |
| source_marked_nonoperative_terminals | 748 |
| retained_body_requests | 0 |
| residual_count | 29165 |
| residual_kind | catalog then unique ordered current official section URLs |
| residual_first_url | first source-ordered current official legis.ga.gov section URL after retained root and 53 title-patch bytes |
| catalog_wave_name | `delegated-toc-title-open-to` |
| residual_wave_name | `source-ordered-current-section-bodies` |
| catalog_acquisition_wave_count | 1 |
| leaf_acquisition_wave_count | 1 |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_ordered_sha256_prefix | source_derived_after_retained_catalog |
| diagnostic_root_rendered_sha256_prefix | a31f9c8 |
| diagnostic_current_locator_digest_prefix | 2b9646e |
| diagnostic_catalog_frontier_digest_prefix | 5d3182a |
| diagnostic_hashes_authorizing | false |
| source_bundle_prefix | af026c4 |

The residual SHA-256 is not a predeclared hex prefix. It is the canonical
JSON digest of the source-ordered unique current official section-URL
array after a retained Title 1–53 catalog. The in-memory audit prefixes
`a31f9c8`, `2b9646e`, and `5d3182a` are diagnostic only: that observation
did not retain the root or 53 title-patch byte strings. Guessing the
remaining hex, emitting a 29,165-URL dump, or inventing a later
`title-99` section fails closed: a static dump would be a forbidden
residual list and would exceed the compact-recipe admission bound.

## Outcome

Georgia is **not** assembler-eligible. Title 1–53 catalog membership is
known from a diagnostic in-memory delegated TOC audit, current identities
are known, and the remaining body wave is an exact 29,165-URL official
section residual. No retained root, no retained title-patch bytes, no
host retained-replay seal, no normalized receipt, no JSON-LD/Parquet
pair, and no current-bundle pair exist for this observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one catalog wave that retains
the root plus 53 title-patch bytes into a fresh directory, then one
global body wave of the resulting current 29,165 official section URLs
(or their drifted successor), then host `--retained-replay-only` of every
parser input with zero network before materialization.

## Catalog-then-body algebra

The Georgia General Assembly delegates the public OCGA table of contents
to the exact Lexis free-public-access container. Exhaustive discovery
reads the rendered root once and issues one nested `open-to` PATCH per
Title 1–53 root. Those 54 catalog inputs are inventory evidence, not
statute bodies. Lexis document routes remain access-gated in automated
sessions; body admission uses the corresponding official
`www.legis.ga.gov` section locators.

A fresh in-memory audit of that delegated TOC at
`2026-08-26T00:34:55Z` closed the exact Title 1–53 catalog:

```text
36,120 nodes
  3,970 expandable nodes closed by 53 title-patch open-to responses
  1 root-rendered HTML observation
```

```text
54 catalog inputs = 1 root GET + 53 title-patch open-to responses
```

Those catalog bytes were **not** retained. Diagnostic hashes from that
audit (`a31f9c8`, `2b9646e`, `5d3182a`) therefore cannot authorize a
ledger. The first residual wave is the catalog itself.

Temporal section locators from that catalog select current identities
and type alternate versions as catalog exclusions:

```text
29,358 temporal section locators
  - 193 alternate temporal versions
  = 29,165 current identities
```

Current identities split as expected operative bodies plus
source-marked nonoperative terminals:

```text
29,165 current identities
  = 28,417 expected operative bodies
  +    748 source-marked nonoperative terminals
```

Zero body requests are reusable. There is no retained strict GA body
ledger, manifest, or content object. The exact prospective body residual
is therefore all 29,165 same-host official section URLs, in source order,
after the retained catalog.

```text
0 retained body requests
  + 29,165 current official section URLs
  = 29,165 body residuals
```

Membership is derived from the retained catalog. It is not
`OFFICIAL_TITLES`, not a filename coverage dump, not a Justia mirror,
and not a later `title-99` hunt.

## Exact remaining URL

The exact next URL is the official delegated container that must be
retained as the catalog root before any body wave:

```text
https://advance.lexis.com/container?config=00JAAzZDgzNzU2ZC05MDA0LTRmMDItYjkzMS0xOGY3MjE3OWNlODIKAFBvZENhdGFsb2fcIFfJnJ2IC8XZi1AYM4Ne
```

The public entry `https://www.lexisnexis.com/hottopics/gacode/` is the
General Assembly landing page for that container. Exhaustive discovery
then issues one `open-to` PATCH per Title 1–53 root and retains those 53
title-patch byte strings beside the root.

The exact next body URL is the first source-ordered current official
`www.legis.ga.gov` section locator derived from that retained catalog.
It is built only as
`official_section_url(section_number)` for a current identity selected
from the Title 1–53 TOC. It is not inferred from legislative-summary
PDFs, from the two-row artifact, from configured title dumps, or from a
guessed later section number.

The exact remaining proof residual is the complete 29,165-URL ordered
current-body difference after those 54 catalog inputs. Recompute that
array only from the retained catalog minus any later-retained current
bodies. A later residual SHA may be recorded only after that derivation
and must use
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## One catalog wave, then one global body wave

Required acquisition shape:

1. Seed a fresh absent evidence root. Do not import legislative-summary
   PDFs, the two-row artifact, the older five-row navigation snapshot,
   the zero-row 2026-08-24 checkpoint, configured title dumps, or Justia
   mirrors (`copied_file_count=0`; never overwrite a prior ledger).
2. Replay exhaustive delegated TOC discovery with retained bytes:
   one root GET of the exact container plus 53 title-patch `open-to`
   responses named `delegated-toc-title-open-to`. Require the same or a
   newly sealed Title 1–53 membership, 29,165 current identities, and
   193 temporal exclusions (or their drifted successor algebra).
3. Derive official same-host section URLs from those current identities
   only. Submit the complete source-ordered unique union as one plural
   batch named `source-ordered-current-section-bodies`.
4. Use one `www.legis.ga.gov` / `legis.ga.gov` Common Crawl inventory
   with URL term `/legislation/georgia-code/`, grouped/coalesced WARC
   reuse, and Wayback prefix inventory. Residual-only retries must not
   repeat grouped archive inventory.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require 29,165 current identities (28,417 operative plus 748
   typed terminals, or the newly sealed successor), first/replay
   frontier equality, and `public_law_no_state_copyright` before treating
   the pair as assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later
  `title-99` section targets;
- importing legislative-summary PDFs (`25sumdoc.pdf`,
  `2024-general-statutes-summary-pdf.pdf`) or the two-row artifact;
- treating the in-memory diagnostic hashes as authorizing without
  retained root and title-patch bytes;
- per-page archive loops, per-title CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming a fenced staging root as current;
- stamping historical archive bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity;
- sole-admitting `OFFICIAL_TITLES`, configured title dumps, or Lexis
  document HTML as the residual body membership.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Georgia binding |
|---|---|
| Source-derived frontier | Delegated Lexis Title 1-53 TOC, then official legis.ga.gov section URLs |
| Fresh evidence generation | Retain root plus 53 title-patches first; never overwrite |
| Direct-only reuse | `--allowed-source-transport direct` |
| One residual wave | unresolved remainder of `source-ordered-current-section-bodies`, 29,165 URLs |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual wave closes:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states GA \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-ga-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-ga-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the delegated catalog root:

```text
https://advance.lexis.com/container?config=00JAAzZDgzNzU2ZC05MDA0LTRmMDItYjkzMS0xOGY3MjE3OWNlODIKAFBvZENhdGFsb2fcIFfJnJ2IC8XZi1AYM4Ne
```

The exact remaining proof residual is the 54 catalog inputs (that root
plus 53 title-patch `open-to` bytes) followed by the complete 29,165-URL
ordered current official-section wave at SHA prefix
`source_derived_after_retained_catalog`.
