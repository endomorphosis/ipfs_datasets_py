# JusticeDAO refresh plan, 2026-10-16

The 2026-10-17 successor is `docs/legal/justicedao_refresh_plan_20261017.md`. The SHA tables below are historical.

Raw law stays on `endomorphosis`. Normalized retrieval stays on `justicedao`. `query_legal_records` selects by the requested jurisdiction. It does not read the caller IP, locale, or country, and it does not read `endomorphosis`.

## Git

`external/ipfs_datasets` fast-forwarded to `origin/main` `96338f30d`. The 144 new commits are LegalIR training and export qualification. They do not add scraper or normalizer files. Local legal edits are still uncommitted.

Direct submodules are at their own `origin/main`. `ipfs_accelerate_py` is `ff69c6dec`. Its uncommitted supervisor edits were replayed onto that tip. Nested gitlinks inside `ipfs_kit_py` were left as they were. Submodule init was not recursive.

`endomorphosis/legal_scrapers` at `210f07376792` (2026-10-15T18:02:12Z) is the Hub copy of scraper work. It is not a new git tree on `origin/main`.

## Live review

Public lists, unauthenticated, 2026-10-16: endomorphosis 276 datasets, justicedao 294. Country gap report `n=262`: current 184, excluded 4, incomplete 27, missing 3, stale 44. Report: `/tmp/grok-barberb/jdq-freshness/gap_report_20261016.json`.

Commit SHA is not content identity. Of the 44 SHA-stale rows, 43 already have `CHECK_EXIT 0` from `jdq_cid_wave5`, which means the normalized entry CIDs match. Do not rebuild those from the commit SHA alone. The one still open is `netherlands_municipal` (1,381,597 rows, source `c936eb059233`). Wave5 is still the scan at bash pid 6457 and python pid 6459. Do not start a second reindex and do not kill that scan.

Leave unpublished: `egypt_governorate`, `south_africa_provincial`, `wallis_futuna`. Leave excluded: Belgium, Portugal, Lithuania, and Ghana national. SHA-matched incomplete rows, including the HTML municipal packs and `uk`, are not source drift. Do not rebuild them with the national `laws.parquet` indexer. Alias spellings stay separate: `north_korea` and `northkorea`, `dominican_republic` and `dominicanrepublic`.

Cards touched on endomorphosis on 2026-10-15 that justicedao does not yet serve as norm repos:

| Source | SHA | Justicedao destination | Present |
| --- | --- | --- | --- |
| `endomorphosis/world_national_law` | `a8fab94c32f3` | `justicedao/world_national_law` | no |
| `endomorphosis/world_municipal_law` | `77298920d9d8` | `justicedao/world_municipal_law` | no |
| `endomorphosis/american_municipal_law` | `24cac8b72a91` | `justicedao/american_municipal_law_norm` | no |

`justicedao/american_municipal_law` exists (`19009d5d2c66`) and stays blocked. `world_law_scanned_pdfs` stays on endomorphosis. Archived, non-official, and `source_official=false` rows stay on endomorphosis.

The same three cards were re-read on 2026-10-16 before the html-only snapshot. `*_html.parquet` is the only payload. `justicedao/world_national_law`, `justicedao/world_municipal_law`, and `justicedao/american_municipal_law_norm` were still absent.

| Source | Live SHA at that read | HTML parquet | Justicedao destination |
| --- | --- | --- | --- |
| `endomorphosis/world_national_law` | `cba1bbb275a9e00b45eceef46e9fa2c54ead039c` | 581 files, 13.93 GiB | `justicedao/world_national_law` |
| `endomorphosis/american_municipal_law` | `24cac8b72a91f1c196bef47a8bd0398b103f26ba` | 12086 files, 6.02 GiB | `justicedao/american_municipal_law_norm` |
| `endomorphosis/world_municipal_law` | `fb60a1397b77899f45b23eb79646a7f43f777147` | measured on the previous pin `08be76fac4a4` as 42342 files, 18.44 GiB | `justicedao/world_municipal_law` |

The downloader re-reads the live SHA for each card and stores it in `/tmp/grok-barberb/jdq-freshness/norm_download_pins.json`. National is pinned at `cba1bbb275a9e00b45eceef46e9fa2c54ead039c` under `~/.ipfs_datasets/country-laws-ir/raw-world/<sha>/world_national_law`. The October 14 tree at `raw-world/world_national_law` is not this revision. American ordinance files are `*_html.parquet`. `*_citation.parquet` is not exported.

`justicedao/american_municipal_law_norm` was uploaded with `upload_folder` at commit `c533c46437e92a51fa1e9aeaf799da3b18ee3801`. It has 11,315,082 rows from source `24cac8b72a91f1c196bef47a8bd0398b103f26ba`. The scratch pin keeps `searchable` false and `revision` null. `justicedao/american_municipal_law` was not changed.

## Atomic corpus

JusticeDAO receives citable legal units. `export_norm` runs `expand_legal_record` before it writes a parquet row. A complete instrument with two or more article or section headings becomes one `legal-record/v1` row per heading. `(a)` and `(1)` stay on the parent section and are indexed in `provenance.subsection`. Chrome that normalizes to empty text increments `not_atomic` and is not written. A null `text` cell is kept with `provenance.atomic` false. The hierarchy locator (`title`, `chapter`, `statute`, `section`, `subsection`, `hierarchy_path`) lives in provenance. It is not a new parquet column.

`query_legal_records` accepts `representation="record"`, `"jsonld"`, or `"text"`. The default `record` view is unchanged, and `representation` is not part of `query_id`. Optional `title`, `chapter`, `section`, and `subsection` select atomic units by the provenance locator. `title` is the title number, not the instrument name. A set locator expands rows before `limit`. Omitted locators leave an existing `query_id` unchanged. `jsonld` is schema.org `Legislation`, and those locators are `additionalProperty` values. `text` is the cleaned unit plus that locator. Neither view reads the caller location. `LEGAL_QUERY_NORMALIZED` stays unset. Pins stay unsearchable.

Parser changes still go through `accept_line_patterns` and the heading lexicon. A model may propose a whole-line chrome pattern. It does not rewrite statute text. Sampling reads justicedao, not endomorphosis, and does not start another reindex.

## Export order

1. Dry-run `export_norm` for one card after that card's html snapshot status is `downloaded`. The 2026-10-16 continue is the go-ahead for these three destinations. Wave5 stays running. Start the dry-run only when `MemAvailable` is at least 16 GiB. A zero-kept Chile or Hungary count stays `not_published`. A card whose dry-run keeps zero rows is not written and not uploaded. Do not pass `--upload`. That flag raises `ExportUploadBlocked`.
2. Write each norm tree locally. Re-read the source SHA the same day. Refuse the upload if it moved.
3. Upload with `huggingface_hub` `upload_folder`, not `upload_large_folder` and not `export_norm --upload`. Ignore cache, token, `.env`, and `.pem` files. `upload_large_folder` in `huggingface_hub` 1.33.0 may split a large folder across commits and cannot delete during upload.
4. Record the destination SHA in a scratch pin file. Leave `searchable` false and `revision` null.
5. Let wave5 finish `netherlands_municipal`. A content diff (`CHECK_EXIT 3`) is the only signal to build and upload that IR.

## Query

`LEGAL_QUERY_NORMALIZED` stays unset. With the flag off, every jurisdiction raises `LegalQueryDisabled` before resolution, including a request that also sets `section`. With the flag on, an unknown code and an unpublished jurisdiction return an empty `legal-record/v1` result, coverage `not_published`, and no US Code rows. A caller environment variable `CLIENT_COUNTRY` does not change that result.

`tests/unit/legal_data/test_query_legal_records.py`: 22 passed on 2026-10-16 after the locator filters. Turning the flag on in a deployment, and marking pins searchable, are still separate go-aheads. Until a world or American norm pin is readable, those families stay `not_published` even if the files exist on the Hub.

## Later the same day

`external/ipfs_datasets` fast-forwarded again to `origin/main` `d56fd69c4`. Those commits are LegalIR qualification evidence. They do not change the legal query or the municipal projector. One-level submodules were already at their own `origin/main`, including `ipfs_accelerate_py` `ff69c6dec`. Dirty local legal files stayed uncommitted. The parent `lift_coding` gitlink was not moved.

On 2026-10-17 the finished v2 tree was uploaded to `justicedao/american_municipal_law_norm` at commit `e12aa185f0e4bc1abed510e771253492b2b54255`: 17,109,229 rows, 856 parts, normalizer `american-municipal-html/v2+legal-record/v1`. A Hub read of `data/part-0000/laws.parquet` at that commit had ordinance text, section `89-3-26`, no `html` column, and no tag remnant. The rows were projected from snapshot `24cac8b72a91`. Live source `110a2c27131d` is not included. The product pin stays unsearchable with revision null.

On 2026-10-18 that Hub tip was replaced by `upload_folder` commit `d50ef57c6cd329c254a094a9396ec29528b920b8`. The public manifest is normalizer `american-municipal-html/v3+legal-record/v1`, 17,109,461 rows, 801 `not_atomic` drops, source snapshot `24cac8b72a91f1c196bef47a8bd0398b103f26ba`. The repo lists 856 `laws.parquet` files and no html payload. A Hub read of `data/part-0000/laws.parquet` at that commit has a bluebook citation, authority City of Hamilton, jurisdiction `US-OH`, hierarchy `Article I / Section 1.01`, schema.org JSON-LD, ordinance text, and no scrape clock. Of the local rows, 16,606,968 have both a place and a state jurisdiction, 502,493 have neither, and none are bare `US`. The product pin stays `revision` null and `searchable` false. `LEGAL_QUERY_NORMALIZED` stays unset. Later live source commits are not in this tree.

The country sampler fleet remains finished at 259 of 259. It is not being started again for chrome patterns. A separate structure audit, `/tmp/grok-barberb/audit_structure_locators.py`, samples a small justicedao corpus shard and counts how many atomic units carry `title`, `chapter`, `section`, and `subsection` into schema.org JSON-LD. It does not upload and does not edit parsers. Parser proposals still need a split test and a negative test before admission.
