# Rhode Island source readiness v2

Date: 2026-08-29

Board: `legal-corpora-reindex-v1`

Task: `LCR-095` source-readiness continuation

Base: `b0ef663d2f17b745777240780c08321dc9a74415`

Status: **nested catalogs closed; exact body wave derived and held; no full
corpus seal; no publication authorization**

This report continues, but does not rewrite, the historical residual record in
`rhode_island_residual_closure_v1.md`.  The exact 29-catalog residual is now
retained.  A production zero-network traversal derives the complete current
section frontier.  The large body acquisition was not launched while other
root-controlled corpus work was active.

## Exact outcome

| Field | Value |
|---|---|
| jurisdiction | `RI` |
| official_root | `https://webserver.rilegislature.gov/Statutes/` |
| source_seed_root | `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260828-ri-evidence-6nKICq` |
| evidence_root | `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ri-readiness-NycEJa` |
| source_seed_parser_inputs | `3018` |
| source_seed_bytes | `13860568` |
| source_seed_projection_sha256 | `7931195b9386a3e3e8f78ab3424c9d87b2f2ef6909695848d314dae46fbf9145` |
| source_seed_zero_network_replayed_inputs | `3018` |
| seed_migration_receipt_sha256 | `b510a5b0c341bf876438a06e2475a16dbf8976ff4834a93cdcb2bb2e00ca9618` |
| seed_hardlinked_files | `6036` |
| seed_copied_files | `0` |
| seed_network_requests | `0` |
| nested_catalog_count | `29` |
| nested_catalog_url_array_sha256 | `1b8cf9c0d27a7e8eae3308f7d64fbd8c4dcaec9b320aa382966cc6db5eca66af` |
| nested_catalog_direct_successes | `29` |
| nested_catalog_bytes | `125303` |
| nested_catalog_archive_fallbacks | `0` |
| nested_catalog_receipt_array_sha256 | `c9fb1f43d12fea54fe85fd9ce3caaa2d77b62a4f58f7c059740008622b04b4d6` |
| nested_catalog_content_array_sha256 | `b3bdcda8f462c557fbd852a939b172b55be1ba1af6989adde63f554624e74584` |
| catalog_parser_inputs_after_closure | `3047` |
| bounded_current_body_proofs | `1` |
| retained_parser_inputs_now | `3048` |
| retained_bytes_now | `14036064` |
| retained_projection_sha256_now | `9bc5071e1646a348ea6f882afc782957dab19e59458c63a57ac3a5ad5049afed` |
| complete_section_frontier_count | `34419` |
| known_pre_nested_sections | `34184` |
| newly_exposed_nested_sections | `235` |
| complete_section_url_array_sha256 | `4c2fa02dde61ed6ca3871b1ac2c9c615b5c8155bb8c324c07a8aa66cf3351985` |
| section_identity_array_sha256 | `9fc6ea73910d20cbfb9bf007748ad572c89c473781cb28e853224a03b2699642` |
| retained_section_bodies | `1` |
| missing_body_count | `34418` |
| missing_body_url_array_sha256 | `f9813a1a727d99d694ce7118d33dafa69544dacf378f8fde3192bfb2370d9729` |
| temporal_locators | `69` |
| typed_terminal_chapters | `6` |
| source_bound_chapter_range_materials | `2` |
| known_current_source_gap_count | `0` |
| unobserved_missing_body_status_count | `34418` |
| catalog_replay_network_requests | `0` |
| large_body_acquisition_started | `false` |
| expected_complete_parser_inputs | `37466` |
| current_bundle_sealed | `false` |
| publication_authorized | `false` |
| authoritative_frontier_manifest_sha256 | `23edd033d64e2bcfc95fd9703190e3e44e11f4515d652d3d6906ff599f5d1038` |
| terminal_classification_audit_sha256 | `6abd04994d6ca589e194658e3d887d715b59d06e79ae7003c3432c5d7bc1f027` |
| source_linked_body_proof_sha256 | `9e2e54664506e2a43fcf6e89b9d26b21dbcf06c33d0085af22862e338e42cc63` |

The authoritative v5 frontier manifest is the content-addressed file:

```text
/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ri-readiness-NycEJa/RI/audits/source-derived-frontiers/23edd033d64e2bcfc95fd9703190e3e44e11f4515d652d3d6906ff599f5d1038.json
```

It contains the complete ordered 34,419-URL frontier, the ordered 34,418-URL
missing-body difference, all 29 catalog receipt and body identities, the exact
parser source hashes, and the retained bounded body proof.  Its filename is
the SHA-256 of its 5,115,827 canonical JSON bytes.  This is a source-readiness
audit manifest, not a complete corpus closure receipt.

## Seed and catalog acquisition

The original retained root was loaded direct-only and replayed every exact
request with no network access.  It contained 3,018 unique HTTP-200 parser
inputs and 3,018 unique content objects:

```text
3,018 = 1 root + 49 title + 2,817 chapter + 151 part catalogs
```

All requests were canonical `GET` requests whose sanitized URL equaled the
receipt endpoint.  The seed into the fresh root used 6,036 hardlinks, copied
no files, and performed no network I/O.  Its immutable migration receipt is:

```text
RI/migrations/b510a5b0c341bf876438a06e2475a16dbf8976ff4834a93cdcb2bb2e00ca9618.json
```

Retained traversal reproduced the ordered 29-catalog array at its previously
pinned SHA.  The entire source-ordered array was then submitted once as the
plural `subpart-index` wave.  Direct acquisition succeeded for all 29 URLs:
29 network requests, 29 direct parser inputs, 125,303 bytes, zero Common Crawl
queries, zero Wayback queries, zero retries, and zero unresolved URLs.  The
ledger retains every individual receipt; their ordered array and the ordered
content-digest array are bound by the table above and embedded in the v5
manifest.

## Zero-network frontier proof

With the 29 inputs installed, the production scraper replayed only retained
bytes.  The transport method was replaced with a fail-if-called sentinel.  It
completed these exact catalog waves before the held body wave:

```text
root-index       1
title-index     49
chapter-index 2817
part-index     151
subpart-index   29
sections     34419
```

The complete section algebra is:

```text
34,419 complete source-derived bodies
  = 34,184 bodies known before nested-catalog closure
  +    235 bodies exposed by the 29 retained catalogs
```

The 235 additions are source-grouped as 32 in Title 6A chapter 2.1, 125 in
Title 6A chapter 9, 31 each in Title 7 chapters 12.1 and 13.1, and 16 in Title
15 chapter 23.1.  There were no repeated section URLs or logical identities.
The source order starts at Title 1 section 1-1-1 and ends at Title 47 section
47-16-1.

One catalog contains an exceptional source link:

```text
catalog: TITLE6A/6A-9/6A-1/6A-1/INDEX.htm
catalog body SHA-256: d63b33c61f1abf9650be1e9761a314a1ddda6d8d11dd55ac5e335ee66de09c3e
href: %C2%A7_6A-9-102.htm
label: § 6A-9-102. Definitions.
```

The parser now admits that locator only for the exact title, chapter, part,
subpart, catalog digest, href, and label tuple.  It preserves the official
source-linked URL while resolving the logical cite to `6A-9-102`.  Drift in
any bound field fails closed.  A production-style request to that exact URL
returned the current 50,193-byte body directly; the guessed normalized sibling
returned 404 and is not substituted.  Strict parsing produced operative
§ 6A-9-102 with no terminal disposition.  The retained proof is:

```text
receipt SHA-256: f8aaadc369a1098e082585accdf329ce565a79af82221e7346b31c205ce7c5fd
body SHA-256:    0519913c5d504420b1e3a9526d59e3e76d47414797abf967577ef41b7c372ca2
transport:       direct
retrieved:       2026-08-29T01:03:12.830000+00:00
```

A default-curl probe had produced a client-sensitive 404 for the same linked
URL.  It does not override the retained production receipt.  Audit
`9e2e54664506e2a43fcf6e89b9d26b21dbcf06c33d0085af22862e338e42cc63`
explicitly supersedes that nonauthorizing diagnostic classification.
This closes the only catalog-parse gap observed in the 29-input wave.  It does
not preclassify the transport or body status of the other 34,418 held URLs;
those remain unobserved until the coordinated acquisition runs.

## Conservative terminal classifications

Catalog replay classifies exactly six anchor-free official chapter wrappers:

| Chapter | Disposition | Content SHA-256 |
|---|---|---|
| 5-20.1 | `reserved_chapter_range` | `4958faff8dc2abc9f1cafca19605d4e72dfacb967ba9cb1237a44187443966e9` |
| 15-27 | `reserved` | `0c3fd9700b7d381a68b0cffca9ff8389560356e3c96adee4709879b4b4de6569` |
| 35-19 | `reserved` | `da3c39c70bc999cb012c44272f43276eebc47a406c3d73dd91fc591132f2a068` |
| 40.1-8.1 | `reserved_chapter_range` | `c66b9364de9282750244f4e1346111759b046e6f8f3b9fab92c46a13ee51b8f3` |
| 40.1-11 | `reserved_chapter_range` | `56542c02750d758dc04f0577116a7be5ec8763b30d83603ffe29486cff155a2f` |
| 40.1-24.1 | `reserved_chapter_range` | `0c49a45e44aaedd55393575d5668720b79821158786521b2657455d3b6e130dd` |

Two source-linked chapter-range materials remain in the section frontier for
later exact body classification; they do not authorize operative statute rows:

| Source URL | Disposition |
|---|---|
| `https://webserver.rilegislature.gov/Statutes/TITLE6/6-3/3.htm` | `repealed_chapter_range` |
| `https://webserver.rilegislature.gov/Statutes/TITLE6/6-18/18.htm` | `repealed_and_transferred_chapter_range` |

The content-addressed terminal audit is:

```text
/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ri-readiness-NycEJa/RI/audits/catalog-terminal-classifications/6abd04994d6ca589e194658e3d887d715b59d06e79ae7003c3432c5d7bc1f027.json
```

## Held body wave and eventual proof

The one bounded body proof leaves this exact difference:

```text
34,418 missing bodies
SHA-256 of canonical ordered URL array:
f9813a1a727d99d694ce7118d33dafa69544dacf378f8fde3192bfb2370d9729
```

No part of that large wave was launched.  A root-controlled operator may run
it only after conflicting corpus work is clear and host available memory is
above 30 GiB.  Both output roots below must be fresh and absent.  The evidence
root is the exact retained root from this report.

Live-to-retained acquisition command:

```bash
STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS=0 \
STATE_SCRAPER_RI_FRONTIER_RESIDUAL_RETRY_ATTEMPTS=0 \
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states RI \
  --scrape \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root /home/barberb/.ipfs_datasets/state_laws/staging-ri-current-live-v1 \
  --acquisition-evidence-root /home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ri-readiness-NycEJa \
  --parallel-workers 1 \
  --json
```

Expected parser-input algebra after a successful complete acquisition is:

```text
37,466 unique parser inputs
  = 3,047 catalogs
  + 34,419 source-derived section bodies

3,048 inputs are already retained
  = 3,047 catalogs + the bounded § 6A-9-102 body

34,418 bodies remain in the exact held difference
```

Any unresolved URL, repeated identity, changed catalog frontier, ambiguous
same-request body, or non-source-bound terminal must fail the run.  The final
normalized row count is intentionally not predeclared because current body
terminal classification occurs only after those exact bodies are retained.

Then replay into a second fresh output root with all network paths forbidden:

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
  --output-root /home/barberb/.ipfs_datasets/state_laws/staging-ri-current-replay-v1 \
  --acquisition-evidence-root /home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ri-readiness-NycEJa \
  --parallel-workers 1 \
  --json
```

The replay must resolve all 37,466 exact parser requests from retained evidence
with zero network requests.  It must reproduce the 34,419-URL frontier and
URL-array SHA above, the same canonical output row count and digest, and the
same terminal dispositions before a current-bundle pair can be considered
assembler-eligible.  Neither command publishes remotely or authorizes Hub or
control-plane mutation.
