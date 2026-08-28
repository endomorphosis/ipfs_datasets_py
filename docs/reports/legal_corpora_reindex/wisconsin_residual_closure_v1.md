# Wisconsin residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-105`  
Goal: `LCR-G153`  
Track: `exact51-residual-wave-d`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-105 by recording the exact remaining Wisconsin
sliding-viewer residual: start a fresh acquisition at the one official
root, then close each source-derived chapter and section continuation
wave. Host zero-network replay has not sealed a current-bundle pair.
The six closed-state steps remain the only admitted path. Hub mutation,
a static residual list, a per-page archive loop, the receiptless
historical fetch cache, the older 480-row repaired catalog, chapter PDFs
as HTML-route substitutes, and guessed later continuation URLs are not
admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | WI |
| official domain | docs.legis.wisconsin.gov |
| official entry | `https://docs.legis.wisconsin.gov/statutes/statutes` |
| official_chapter_locator | `https://docs.legis.wisconsin.gov/document/statutes/{chapter}` |
| official_section_locator | `https://docs.legis.wisconsin.gov/document/statutes/{section}` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | source-derived sliding viewer from one official root |
| seed | zero authorizing ledger inputs; start at the official root |
| historical_cache_admission | forbidden |
| receiptless_historical_cache | forbidden |
| repaired_480_catalog | forbidden |
| chapter_pdf_as_html_substitute | forbidden |
| static_residual_list | forbidden |
| invent_later_continuation_urls | forbidden |
| citation_link_344_579_without_toc | forbidden |
| unlinked_source_row_854_30 | leading TOC identity; not a cache miss to drop |
| diagnostic_observation_at | 2026-08-26 |
| diagnostic_root_bytes | 317921 |
| diagnostic_root_sha256_prefix | 66bcea27111f |
| official_source_chapters | 470 |
| repaired_catalog_chapters | 480 |
| initial_chapter_viewers | 470 |
| initial_section_locators | 13396 |
| first_chapter_continuations | 131 |
| first_section_continuations | 834 |
| known_lower_bound_urls | 14832 |
| retained_authorizing_inputs | 0 |
| historical_cache_objects | 14337 |
| historical_cache_bytes | 1402013000 |
| historical_cache_receipts | 0 |
| historical_cache_parser_input_envelopes | 0 |
| cached_initial_operative_bodies | 12561 |
| cached_continuation_required_bodies | 834 |
| source_listed_body_absent_from_cache | 854.30 |
| cached_citation_link_not_in_initial_toc | 344.579 |
| residual_count | 14832 |
| residual_kind | unique ordered viewer URLs from one root; later continuations source-dependent |
| residual_first_url | `https://docs.legis.wisconsin.gov/statutes/statutes` |
| residual_floor_kind | known lower bound; later continuations remain source-dependent |
| later_continuation_count | source_dependent_after_continuation_waves |
| root_wave_name | `statutes-index` |
| chapter_wave_name_prefix | `chapter-toc-wave-` |
| section_wave_name_prefix | `section-body-wave-` |
| residual_wave_name | `source-derived-viewer-continuation-waves` |
| root_acquisition_wave_count | 1 |
| chapter_acquisition_wave_count | source_dependent_at_least_2 |
| leaf_acquisition_wave_count | source_dependent_at_least_2 |
| close_each_source_derived_continuation_wave | true |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_ordered_sha256_prefix | source_dependent_after_continuation_waves |
| diagnostic_hashes_authorizing | false |
| source_bundle_prefix | 02f8bef4e00a |

The residual SHA-256 is not a predeclared hex prefix. It is the canonical
JSON digest of the source-ordered unique viewer-URL array after the
official root and every source-derived continuation wave close. Guessing
that hex, emitting a 14,832-URL dump, or inventing a later
`/statutes/statutes/{chapter}/_60?down=1` continuation fails closed: a
static dump would be a forbidden residual list, later continuations are
source-dependent, and a dump would exceed the compact-recipe admission
bound.

## Outcome

Wisconsin is **not** assembler-eligible. The official root membership is
known from a diagnostic observation, the known lower-bound viewer
frontier is 14,832 URLs, and later chapter and section continuation
membership remains source-dependent. Zero historical cache objects are
admissible as authorizing parser inputs. No host retained-replay seal,
normalized receipt, JSON-LD/Parquet pair, or current-bundle pair exists
for this observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one fresh isolated acquisition
that starts at the official root, closes each source-derived
continuation wave without guessing later URLs, then host
`--retained-replay-only` of every parser input with zero network before
materialization.

## Viewer-frontier algebra

The Wisconsin Legislature sliding viewer is one official root, then
source-derived chapter windows, then source-derived section windows.
Membership comes from retained official catalog/root bytes and each
window's source-bound `Down` continuation, not from
`OFFICIAL_CHAPTERS`, the older 480-row repaired catalog, filename
coverage, or the historical fetch cache.

A diagnostic observation of the official root at
`https://docs.legis.wisconsin.gov/statutes/statutes` is 317,921 bytes
with SHA-256 prefix `66bcea27111f`. That root exposes exactly 470 unique
numeric chapters in source order from chapter 1 through chapter 995.
Those 470 retained initial chapter windows expose 13,396 unique leading
TOC section identities. Of those chapter windows, 131 expose a first
source-bound `Down` continuation. Of the 13,396 initial section
identities, 834 require a first section continuation. No later
continuation window was retained, so final section-locator cardinality
and any later continuation URLs remain unknown until acquisition.

```text
14,832 known lower-bound URLs
  = 1 official root
  + 470 initial chapter viewers
  + 13,396 initial section locators
  + 131 first chapter continuations
  + 834 first section continuations
```

```text
13,396 unique leading TOC identities
  = 12,561 complete initial operative bodies in the historical cache
  +    834 continuation-required initial bodies in the historical cache
  +      1 source-listed § 854.30 absent from that cache
```

The 12,561 / 834 split is a parser-oracle classification of historical
bodies. It is not an authorizing ledger. Terminal counts for the
complete corpus remain unknown until the continuation graph closes.

The residual is therefore the entire eventually discovered viewer
frontier. Within the known lower bound, every one of the 14,832 URLs is
residual for certification. Later continuations discovered from those
131 chapter `Down` links and 834 section `Down` links are additional
residuals. They are not guessed.

## Historical cache is not a seed

The largest historical Wisconsin fetch cache contains 14,337 unique URLs
and 14,337 unique content digests totaling 1,402,013,000 declared bytes.
Its URL classes are one root, 470 chapter HTML pages, 470 redundant
chapter PDFs, and 13,396 section HTML pages. All were recorded as
`requests_direct`. Recorded size and SHA-256 values match their bodies.

Those cache records contain only `cached_at`, `provider`, `sha256`,
`size`, `state_code`, and `url`. They contain no authorizing transport
receipt, sanitized request, response status/headers, or retained
parser-input envelope. Consequently:

```text
14,337 historical cache objects
  + 0 transport receipts
  + 0 parser-input envelopes
  = 0 authorizing ledger inputs
```

Zero historical cache objects may be silently promoted into publication
evidence, seeded as `--allowed-source-transport direct` inputs, or
replayed under `--retained-replay-only`. They remain useful as offline
parser fixtures. They cannot close a current-bundle pair.

Two earlier Wisconsin caches (5,014 and 6,085 URLs) are complete URL
subsets of the 14,337-object cache and inherit the same receiptless
defect. Prior normalized derivatives (12,894 unique identities and a
160-row published subset) are not parser-input ledgers.

## Exact remaining URL

The exact next URL is the official statutes root. Fresh acquisition
starts there and nowhere else:

```text
https://docs.legis.wisconsin.gov/statutes/statutes
```

That GET is the `statutes-index` wave. The adapter then submits the
source-ordered chapter locators derived from that root as
`chapter-toc-wave-1`, follows each source-bound `Down` as a later
`chapter-toc-wave-N` until every chapter body begins or is typed
terminal, then submits the complete source-ordered section union as
`section-body-wave-1` and follows each source-bound section `Down` as a
later `section-body-wave-N`. Membership is `toc_chapter_links(root)` and
`parse_wisconsin_chapter_frontier_window` / `parse_wisconsin_section_window`
on retained windows. It is not `OFFICIAL_CHAPTERS`.

Section 854.30 is source-listed. Its TOC self-link is omitted. Leading
TOC identity still admits the exact
`https://docs.legis.wisconsin.gov/document/statutes/854.30` locator. The
local chapter 854 PDF (SHA-256 prefix `f4694918a3f4`) confirms that the
section is operative, but that PDF is not a substitute for the exact
HTML-route parser input and is not a reason to drop the row.

Section 344.579 was cached after legacy citation-link traversal. It is
not an initial-window TOC row. It must not become a frontier member
unless a retained chapter continuation discovers it.

The exact remaining proof residual is the complete source-ordered unique
viewer-URL array after those waves close. Recompute that array only from
the official root plus each source-derived continuation. A later residual
SHA may be recorded only after that derivation and must use
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## One root wave, then each source-derived continuation wave

Required acquisition shape:

1. Seed a fresh absent evidence root. Do not import the 14,337-object
   receiptless historical cache, the 5,014-URL or 6,085-URL earlier
   caches, chapter PDFs as HTML-route substitutes, the older 480-row
   repaired catalog, or prior normalized derivatives
   (`copied_file_count=0`; never overwrite a prior ledger).
2. Fetch the official root once as `statutes-index`. Require 470 ordered
   numeric chapters (or their drifted successor), not the 480-row
   repaired list.
3. Submit the 470 initial chapter viewers as one plural
   `chapter-toc-wave-1`. Close each source-derived chapter `Down` as a
   later `chapter-toc-wave-N`. Do not invent later continuation URLs.
   The first known chapter-continuation floor is 131 URLs.
4. Derive official same-host section URLs from leading TOC identity,
   including unlinked source rows such as § 854.30. Exclude body
   citations such as § 344.579 unless a retained chapter continuation
   lists them. Submit the complete source-ordered unique union as
   `section-body-wave-1`, then close each source-derived section `Down`
   as a later `section-body-wave-N`. The first known section-continuation
   floor is 834 URLs.
5. Use one `docs.legis.wisconsin.gov` Common Crawl inventory with URL
   terms `/statutes/statutes` and `/document/statutes/`, grouped/coalesced
   WARC reuse, and Wayback prefix inventory. Residual-only retries must
   not repeat grouped archive inventory. There is no per-page archive
   loop and no `archive.is`.
6. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require first/replay frontier equality, closed
   operative-plus-terminal algebra, and
   `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later
  `/_60?down=1` continuation targets;
- admitting the receiptless historical cache, its 470 chapter PDFs, or
  earlier subset caches as authorizing evidence;
- sole-admitting `OFFICIAL_CHAPTERS` or the older 480-row repaired
  catalog as official membership;
- treating § 344.579 as a frontier member from citation-link traversal
  alone;
- dropping § 854.30 because its TOC self-link is omitted;
- substituting chapter PDFs for the exact HTML-route parser input;
- per-page archive loops, per-chapter CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming a fenced staging root as current;
- stamping historical archive bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Wisconsin binding |
|---|---|
| Source-derived frontier | Official root, then chapter and section viewer continuation waves |
| Fresh evidence generation | Start from an absent evidence root; never import the receiptless cache |
| Direct-only reuse | `--allowed-source-transport direct`; historical cache has no direct receipts |
| One residual wave | unresolved remainder of each `chapter-toc-wave-N` / `section-body-wave-N` |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual waves close:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states WI \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-wi-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-wi-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the official statutes root:

```text
https://docs.legis.wisconsin.gov/statutes/statutes
```

The exact remaining proof residual is that root plus the complete
source-ordered unique viewer frontier after each chapter and section
continuation wave closes. The known floor is 14,832 URLs. Later
continuations remain `source_dependent_after_continuation_waves` at SHA
prefix `source_dependent_after_continuation_waves`.
