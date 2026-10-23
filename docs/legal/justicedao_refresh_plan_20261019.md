# JusticeDAO refresh plan, 2026-10-19

The 2026-10-21 plan supersedes the SHA table and git table below. This file stays the record of the 2026-10-19 review.

Raw law stays on `endomorphosis`. Normalized retrieval stays on `justicedao`. A query names the jurisdiction it wants. It does not read the caller IP, locale, or country, and it does not read `endomorphosis`.

This plan is the 2026-10-19 review. The 2026-10-17 plan remains the contract for export gates, excluded slugs, and the query flag. This pass does not flip `LEGAL_QUERY_NORMALIZED`, mark pins searchable, upload a norm tree, or start an export.

## Git pull

`external/ipfs_datasets` is `origin/main` `13061f6783cd2cd7b7ed38080d5c701117643b80`. The four commits after `e9d384ab8` are LegalIR request-bound recovery. They add no scraper or normalizer files. Uncommitted legal edits stayed in the worktree. Nothing was committed. The parent `lift_coding` gitlink was not moved.

Direct submodules were fetched one level, with submodule recursion off.

| Checkout | Result |
| --- | --- |
| `ipfs_datasets` | Fast-forward already landed. `HEAD` equals `origin/main` (`0` behind, `0` ahead). |
| `ipfs_kit_py` and `.tools/ipfs_kit_py` | Already at `origin/main` `40c98c71b`. |
| CEC libraries, multimedia, common-crawl | Already at their `origin/main` tips. They were not rewound. |
| `ipfs_accelerate_py` | Stayed at `ff69c6dec`. A re-fetch the same morning put `origin/main` 71 commits ahead (`fd9189a8a`). The dirty file `agent_supervisor/runtime/grok_cli_runner.py` is also changed on that tip, so the checkout was not merged. |
| Parent `lift_coding` | Stayed at `4586d7e1068c`. `origin/main` is `58d123053e`, 66 commits ahead. The worktree is dirty on submodule gitlinks, so that parent history was not merged. |

## Endomorphosis review

Live tips re-read on 2026-10-19 04:47 UTC from `repo_info`, and again at 04:51 UTC. Both reads returned the same SHAs. The earlier same-day tips (`a505287b`, `2ba22816`, `6e105b1b`, `974d704d`) had already moved.

| Repo | SHA | Last modified | Justicedao destination |
| --- | --- | --- | --- |
| `endomorphosis/world_national_law` | `c716d63911e8709d843bfbe53fc4abf44d88becb` | 2026-10-19 04:44:46Z | absent |
| `endomorphosis/world_municipal_law` | `976c8554ed14021ab9a3ac41480c2616d18efb3d` | 2026-10-19 04:44:43Z | absent |
| `endomorphosis/american_municipal_law` | `d2a4c3b744ce129cfa4a5a82f301a0ba1ee78578` | 2026-10-19 01:01:23Z | norm repo present, see below |
| `endomorphosis/legal_scrapers` | `8295eebd6fb75202e89fdeefe423bd3ba6bf9cc6` | 2026-10-18 21:28:32Z | source, vendored below |
| `endomorphosis/world_law_pipeline` | `e5f232368ddcb7483a471f1de4128c03c8255513` | 2026-10-19 01:42:57Z | source, vendored below |

`justicedao/american_municipal_law_norm` is `df0c0c405bf59cb948d1269dea29767a4712fb81` (2026-10-19 14:17:23Z), normalizer `american-municipal-html/v4+legal-record/v1`, source snapshot `24cac8b72a91`. The previous tip `d50ef57c6cd329c254a094a9396ec29528b920b8` is v3. The scratch pin in `/tmp/grok-barberb/jdq-freshness/norm_upload_pins.json` stays `searchable` false and `revision` null. `justicedao/american_municipal_law` stays blocked at `19009d5d2c66`. Do not upload another American tree over `df0c0c40`, and do not treat this card as live source `d2a4c3b7`.

`world_law_scanned_pdfs` stays on endomorphosis. Archived, non-official, and `source_official=false` rows stay on endomorphosis. Belgium, Portugal, Lithuania, and Ghana national stay unpublished as query routes. `egypt_governorate`, `south_africa_provincial`, and `wallis_futuna` stay unpublished.

A 2026-10-18 sample of the world cards against JusticeDAO GraphRAG manifests is in `/tmp/grok-barberb/world-gap-sample/sample_report.json`. National has 205 configs and 205 provenance rows. Municipal has 89 configs and 88 provenance rows; Hungary is the config with no provenance row, and `justicedao/ipfs_hungary_municipal_laws_ir` is absent. Thin national cards have larger `embedded` indexes. Sri Lanka is still `partial`. Four sampled corpus shards have nonempty `body` and instrument identity, and `source_url` is an empty string. That sample did not write card rows.

## Exports

The American v4 export of sampled pin `24cac8b72a91` finished locally and was uploaded with `upload_folder` to `justicedao/american_municipal_law_norm` at `df0c0c405bf59cb948d1269dea29767a4712fb81`. Normalizer `american-municipal-html/v4+legal-record/v1`. The log records `SOURCE_MOVED`: live source `d2a4c3b7` was not exported. Rows kept 17,109,461. Every local file matches the Hub object size. Do not start another American export of this pin.

No municipal or national export was running. Disk on `/home` at the earlier check was 165 GiB free of 850 GiB.

Local trees that must not be uploaded as the current card:

| Tree | Why it stays local |
| --- | --- |
| `norm-export/9544a706bdc5/world_national_law` (12 GiB) | Live national commit is `c716d639`, not `9544a706`. |
| `norm-export/0c715ba7a917/...` (23 GiB) | Live municipal commit is `976c8554`, not `0c715ba7`. |
| `norm-export/24cac8b72a91/american_municipal_law_v4` | Already uploaded as `df0c0c40`. Do not upload it again. |
| `110a2c27131d` (8.3 GiB) and the older American trees under that pin | Not the v4 card. The live American source is `d2a4c3b7` and was not exported. |

`export_norm --upload` still raises `ExportUploadBlocked`. An upload uses `upload_folder` only. World destinations are absent, and the finished local world trees are not the live SHAs (`c716d639` national, `976c8554` municipal), so they are not uploaded. Do not start another world export from those older pins.

## Query from anywhere

`query_legal_records` checks `LEGAL_QUERY_NORMALIZED` before jurisdiction resolution. The flag defaults off and raises `LegalQueryDisabled`. With the flag on, the requested jurisdiction selects the justicedao repo. An unknown or unpublished jurisdiction returns an empty `LegalQueryResult`, coverage `not_published`, and no US Code rows. `CLIENT_COUNTRY` does not change the result. There is no geo-IP branch. The reader does not fall back to endomorphosis.

A caller can name the municipality with `place`, decimal `latitude` and `longitude`, or both. Those arguments are the place whose law is requested. They are not the caller's location and they do not register a new jurisdiction route. On the US municipal corpus, names and coordinates resolve through the primary GNIS seed. A name that matches several cities needs a state suffix or a coordinate within 25 km of one of those cities. Coordinates never switch the request to a different name. `Ventura` stays the California city. A caller-supplied latitude and longitude, or a city name's own seed point, also names the Census county or county-equivalent that contains the city, and the territory when the point is in one, and returns that government's stored ordinances beside the city ordinances. A tied city coordinate does not pick a city, and a missing county code is not invented. `as_of` keeps rows whose `effective_date` is a calendar day on or before that `YYYY-MM-DD`. A missing effective date does not match, and this is not a repeal check. `title`, `chapter`, `section`, and `subsection` can be the whole query. `title` remains the title number. The legal-record columns are unchanged: place is `authority` plus `US-{state}`, and the date is `effective_date`. JSON-LD still exposes that date as `legislationDate` and does not add `dateModified`.

World and American norm repos open only when `justicedao_release_pins.json` marks that repo searchable with a 40-hex revision. On 2026-10-19 the user opened `american_municipal_law_norm` at `df0c0c405bf59cb948d1269dea29767a4712fb81`. `world_national_law` and `world_municipal_law` stay `searchable` false and `revision` null. `LEGAL_QUERY_NORMALIZED` defaults on. Set it to `0` to stop before jurisdiction resolution.

`retrieval` `keyword` or `vector` searches the municipality selected by `place` or by decimal `latitude` and `longitude`. Keyword search keeps a row only when every query token is present. Vector search ranks that same section with a binary token vector of 2^20 buckets and a query-normalized integer inner product. Counts are not stored, so a repeated word cannot outrank a section that contains the query terms. It does not download an embedding model. When the caller does not pass a corpus opener, the American route reads the local v4 shards for that authority and does not contact the Hub.

`query_legal_records` does not import `hub_integrated` or `world_municipal`. Place and date filters were added in that module. The product pin for `american_municipal_law_norm` is searchable at `df0c0c405bf59cb948d1269dea29767a4712fb81`. `LEGAL_QUERY_NORMALIZED` defaults on. Set it to `0` to disable resolution.

## Package integration

Hub code that changed after the 2026-10-17 pins is now under `legal_scrapers/hub_integrated/`. 284 source files were written (Python, Markdown, and the updated text-preservation patch). `python -m compileall` on the pipeline tree and the new normalizer tree exited 0. The third-party Preeti mapper warns about invalid escape sequences and still compiles. No token value was copied.

| What landed | Where | Source |
| --- | --- | --- |
| Text-preservation notes, `gates_stream.py`, vector-repack helpers, and `text_preservation_v3.2` through `v3.4.3` (`normalize.py`, `structure.py`) | `hub_integrated/legal_scrapers/normalizers/` | `legal_scrapers` `8295eebd` |
| Updated `text_preservation.patch` (33,005 bytes) and `test_text_preservation.py` | same directory | same |
| New and changed pipeline scrapers: EU, states, UK/IE, Philippines, OCR, Africa/Middle East, South Asia, municipal web crawlers, archive fetcher, place-code builders | `hub_integrated/world_law_pipeline/` | model `974d704d`, then the 04:47 UTC delta below |

Left out of the package on purpose:

- Backup trees (`bak_20261018_*`), probe scripts, shell campaign wrappers, and JSON caches.
- Upload helpers `upload_pdfs.py`, `sync_code.py`, and `hf_import*.py`.
- The live `country_laws_ir` tree. Local `structure.py` is 89,820 bytes and local `normalize.py` is 48,549 bytes. Hub `text_preservation_v3.4.3/structure.py` is 109,831 bytes and its `normalize.py` is 43,431 bytes. Those Hub copies sit beside the live normalizer. They were not applied, and the patch was not applied.
- `national_collectors/collect_td.py` (22,071 bytes). The Hub shared copy is 22,528 bytes and is stored under the pipeline mirror, not written over the catalogued collector.
- LawMa and LawMaToo weights. justicedao still has no models to vendor.

`hub_integrated/__init__.py` records `8295eebd` and `e5f232368`. Importing it does not import the collectors. Several vendored scrapers still default `WORLD_LAW_ROOT` to `/workspace/world_law` when the variable is unset. Query does not load them.

The pipeline tip moved from `974d704d` to `e5f232368` at 2026-10-19 01:42 UTC. The blob diff is 2 added files and 8 changed files. The scraper modules `scrapers/states/adapters.py` (187,439 bytes), `common.py`, and `de_sh_wb.py`, plus the four changed READMEs, were copied into `hub_integrated/world_law_pipeline/` and compile. Shell files `status.sh` and `_sh_after_check.sh`, and the CDX check `_sh_cdx_check.py`, were not copied. `legal_scrapers` was still `8295eebd`, so the normalizer tree from the earlier pass was left as it is. `country_laws_ir` was not edited while the American v4 export is running.

## What is still gated

1. Do not upload `9544a706`, `0c715ba7`, `24cac8b72a91`, or `110a2c27131d` as the current world or American card.
2. Do not start a second export of `c716d639` or `976c8554`, and do not start a second American writer beside pid 1237811, until a go-ahead accepts that the source commit may move during the run, or the drops pause and a same-day re-read still matches.
3. `american_municipal_law_norm` is searchable at `df0c0c405bf59cb948d1269dea29767a4712fb81`. Leave every other norm pin `searchable` false and `revision` null until a go-ahead names that repo.
4. `LEGAL_QUERY_NORMALIZED` defaults on. Set it to `0` to disable resolution. World pins stay closed.
5. Merging `ipfs_accelerate_py` waits until `grok_cli_runner.py` can be merged without dropping the uncommitted supervisor runner.
6. Applying `text_preservation_v3.4.3` onto `country_laws_ir` waits for a named go-ahead and tests. This pass did not edit `structure.py`.
