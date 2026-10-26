# JusticeDAO refresh plan, 2026-10-17

The 2026-10-19 successor is `docs/legal/justicedao_refresh_plan_20261019.md`. The SHA tables below are historical.

Raw law stays on `endomorphosis`. Normalized retrieval stays on `justicedao`. A query names the jurisdiction it wants. It does not read the caller IP, locale, or country, and it does not read `endomorphosis`.

This plan reviews the Hub legal datasets, records the git pull, states what can be published, and records the scraper and normalizer code that moved into the `ipfs_datasets_py` package. It does not flip `LEGAL_QUERY_NORMALIZED`, mark pins searchable, upload a norm tree, or stop the exports that are already running.

## Git pull

`external/ipfs_datasets` fast-forwarded `4a410373a..e9d384ab8` onto `origin/main`. Those five commits are LegalIR archival and dead-owner recovery. They do not touch legal scrapers, the query path, or the norm exporter. Uncommitted legal edits stayed in the worktree. Nothing was committed. The parent `lift_coding` gitlink was not moved. The parent itself is one commit behind `origin/main` `e18ce337` and its worktree is dirty, so that parent commit was not merged.

Direct submodules were fetched one level, with submodule recursion off.

| Checkout | Result |
| --- | --- |
| `ipfs_kit_py` and `.tools/ipfs_kit_py` | Already at `origin/main` `40c98c71b`. Dirty nested gitlinks were left. |
| `ipfs_accelerate_py` | Stayed at `ff69c6dec`. `origin/main` is `eaaec0ac5`, 65 commits ahead. The only overlapping dirty file is `agent_supervisor/runtime/grok_cli_runner.py`, which holds the uncommitted supervisor runner. That checkout was not merged. |
| CEC libraries | Already ahead of their `origin/master` tips. They were not rewound. |
| multimedia and common-crawl | Already at their own `origin/main`. |

## Endomorphosis review

Live dataset tips read on 2026-10-17 after 19:30 UTC:

| Repo | SHA | Justicedao destination | On justicedao |
| --- | --- | --- | --- |
| `endomorphosis/world_national_law` | `faa17aa5bbd84ec2ca65d3c00318b001a3c2c504` | `justicedao/world_national_law` | absent |
| `endomorphosis/world_municipal_law` | `00ef80f4cd7a6528592741ca571915af733e4af3` | `justicedao/world_municipal_law` | absent |
| `endomorphosis/american_municipal_law` | `e915772a9cd8e6e3fa3ceff2337be0eed1a1aad9` | `justicedao/american_municipal_law_norm` | present at `e12aa185f0e4` |
| `endomorphosis/legal_scrapers` | `c3a8fc1e90888312f6dc3d76e04604936f1e02f3` | not a retrieval card | source code, vendored below |

`justicedao/american_municipal_law_norm` at `e12aa185f0e4bc1abed510e771253492b2b54255` was the published v2 tree on 2026-10-17: 17,109,229 rows, normalizer `american-municipal-html/v2+legal-record/v1`, source snapshot `24cac8b72a91`. On 2026-10-18 `upload_folder` replaced that tip with `d50ef57c6cd329c254a094a9396ec29528b920b8` (v3, 17,109,461 rows, source `24cac8b72a91`). Do not upload the null-text commits again. `justicedao/american_municipal_law` stays blocked at `19009d5d2c66`. `world_law_scanned_pdfs` stays on endomorphosis. Archived, non-official, and `source_official=false` rows stay on endomorphosis.

Country IR repos are a separate lane. The 2026-10-16 gap report is historical. Belgium, Portugal, Lithuania, and Ghana national stay unpublished as query routes. `egypt_governorate`, `south_africa_provincial`, and `wallis_futuna` stay unpublished. SHA-matched HTML municipal packs are not rebuilt with the national `laws.parquet` builder. Alias spellings stay separate scrapes.

Hub models: `endomorphosis/world_law_pipeline` at `a37e6c1f9bbff47f3a3c175668f1f737110209f1` holds scraper and loader source, and that source is vendored below. `endomorphosis/LawMa` and `endomorphosis/LawMaToo` have no parser source. The justicedao model listing returned no repos.

## Exports already running

These processes were already running. They were not restarted and not stopped.

| Job | Pid | Pin it is writing | Live source now |
| --- | --- | --- | --- |
| American v3 `export_norm --family american` | 2361754, parent bash 2361735 | `24cac8b72a91` into `american_municipal_law_v3` | `e915772a` |
| Municipal parallel, 6-worker parent | 2397327 | `0c715ba7a917` under `.shards-world_municipal_law` (about 12 GiB, 1502 `laws.parquet` files at the last count) | `00ef80f4` |

A later check the same evening still had the American writer on file 5953 of 12086 (`1217078_html.parquet`) and the three municipal workers past file 12290 of about 14585. The municipal shard directory held 1779 `laws.parquet` files, about 14 GiB, on pin `0c715ba7`. Those jobs are exporting the sampled pins even though the live commits have moved. The American tree is a later projector of snapshot `24cac8b72a91`. It is not the live source `e915772a`, and it is not an upload.

A national shard directory exists at pin `9544a706bdc5` (about 12 GiB, 1196 `laws.parquet` files) and has no running writer. The live national commit is `faa17aa5`. That directory is not uploaded and is not restarted on top of the municipal and American jobs.

`export_norm --upload` still raises `ExportUploadBlocked`. An upload uses `upload_folder` only after a finished local tree, a same-day source SHA that still equals the tree's `source_revision`, a destination that does not already exist, and a named repo. `justicedao/american_municipal_law_norm` already exists, so the upload script refuses it. World destinations are still absent, and the in-progress trees are not the live SHAs, so they are not uploaded.

Disk at the later check: about 136 GiB free on `/home`, 84 percent used. `MemAvailable` was about 43 GiB. Do not start a second national, municipal, or American export while these jobs hold the disks.

## Query from anywhere

`query_legal_records` is the worldwide entry. `LEGAL_QUERY_NORMALIZED` defaults off. With the flag off, every call raises `LegalQueryDisabled` before jurisdiction resolution, including an unknown code and including a call that also sets `section`.

With the flag on, the requested jurisdiction selects the justicedao repo. An unknown or unpublished jurisdiction returns an empty `LegalQueryResult`, coverage `not_published`, and no US Code rows. `CLIENT_COUNTRY` does not change the result. There is no geo-IP branch. A stale justicedao export is still served from justicedao. The reader does not fall back to endomorphosis.

World and American norm repos open only when `justicedao_release_pins.json` marks that repo searchable with a 40-hex revision. Those pins stay `searchable` false and `revision` null. Turning the flag on in a deployment is a separate go-ahead that names the repos. Until then, a file that exists on the Hub is not served.

`representation` is `record`, `jsonld`, or `text`. The default record view is unchanged, and `representation` is not part of `query_id`. Locator filters (`title`, `chapter`, `section`, `subsection`) select atomic units. `title` is the title number. GB stays on `justicedao/ipfs_uk_laws_ir`. US plus statute and no `admin_level` is an error when the resolved level is not `adm1`. `US-CA` is `not_published`, not that error.

`tests/unit/legal_data/test_query_legal_records.py` already covers the client-location case. This pass did not change that module.

## Package integration

Hub code that was missing from git is now in the package. Sandbox paths (`/workspace` and `/home/box`) were rewritten to `IPFS_DATASETS_LEGAL_CORPORA_ROOT` and `IPFS_DATASETS_LEGAL_COLLECTORS_ROOT`. No token file was copied. Upload helpers were not added beside the gated `upload_folder` path.

| What | Where | Source |
| --- | --- | --- |
| 19-column municipal normalizer (`schema`, `normalize`, `jurisdiction`, `text_quality`, `parquet_io`, `catalog`) | `legal_scrapers/world_municipal/` | `legal_scrapers` `c3a8fc1e` |
| Municipal campaign collectors | `legal_scrapers/world_municipal_campaigns/` (163 Python files) | same dataset |
| Switzerland, Denmark, Finland, Greece, Ireland, Luxembourg, and Slovakia municipal collectors, plus shared municipal helpers | `legal_scrapers/hub_integrated/legal_scrapers/municipal/` (42 files) | same dataset |
| `pack_raw_for_ir.py`, `test_text_preservation.py`, `NORMALIZER_VERSION.md`, `SCHEMA.md` | `legal_scrapers/hub_integrated/legal_scrapers/` | same dataset |
| Pipeline scrapers, archive fetcher, place-code builders, and loader that were not already in git | `legal_scrapers/hub_integrated/world_law_pipeline/` (133 Python files) | model `a37e6c1f` |
| Newer `archive_fallbacks.py`, `common.py`, `world_lib.py`, `world_package.py` | `national_collectors/` and the harvested helper copies | `legal_scrapers` scrapers tree |
| Sri Lanka and Serbia collectors, plus `pdf_extract_lib.py` | `national_collectors/` from the harvested copies, which match the Hub text | same |
| Afghanistan, Madagascar, South Sudan, Venezuela | `national_collectors/` and the catalog | full harvested collectors |

The Hub copies of `collect_mg.py` and `collect_ve.py` are stubs. The package kept the full harvested collectors (916 and 528 lines) and catalogued those. Afghanistan and South Sudan match the Hub text. The catalog rows point at `endomorphosis/ipfs_afghanistan_laws`, `ipfs_madagascar_laws`, `ipfs_southsudan_laws`, and `ipfs_venezuela_laws`, plus the matching `justicedao` IR ids.

`country_laws_ir` on the Hub dataset is an older snapshot. Local `structure.py`, `normalize.py`, `profiles.py`, and the other dirty IR modules are larger. They were not replaced. The Hub `text_preservation.patch` and `shard_support.patch` were not applied onto that newer tree.

`hub_integrated` records the two source SHAs and does not import the collectors when the package imports. `query_legal_records` does not import `world_municipal` or `hub_integrated`.

Tests run after the vendor:

- `tests/unit/world_municipal`: 58 passed, with `--confcutdir` set to that directory so its `wm` fixture loads.
- `tests/unit/legal_scrapers/test_national_collectors.py`: 5 passed, including `load_collector_module("at")`.

A second pass the same evening re-read the Hub tips. `legal_scrapers` was still `c3a8fc1e` and `world_law_pipeline` was still `a37e6c1f`. `datasets` HEAD was still `e9d384ab8`, equal to `origin/main`. `ipfs_accelerate_py` was still 65 commits behind, with the same dirty `grok_cli_runner.py` overlap, and was not merged.

Collectors that already lived under `international/harvested/shared/` and were absent from `national_collectors/` are now copied there and catalogued. That added 73 gazette collectors, including Syria (`collect_sy.py`, archive-only, Hub HOLD). Sandbox tessdata paths in those collectors now use `IPFS_DATASETS_TESSDATA`, defaulting to `~/.ipfs_datasets/tessdata`. `harvest.py` rewrites that path on future harvests. The ISO lookup for Botswana is `collect_bw.py`. `collect_bw_archive.py` stays available by module name.

Eleven more Hub package files that were not on disk were placed beside the live modules: Andorra, Eritrea, North Korea, Liechtenstein, Monaco, and San Marino collectors; Botswana, Portugal, and Lithuania archive wrappers; `archive_harvest.py`; and the two municipal publisher modules `codepublishing.py` and `municipalcodeonline.py`. Hub ids are filled only when a harvested dataset folder confirmed the slug. Andorra, Eritrea, Liechtenstein, Monaco, and San Marino have no harvested folder here, so their catalog rows do not invent a Hub id. North Korea's collector records source type `38north_nk_techlab`. It is in the package and is not a JusticeDAO publish path.

`national_campaigns/` (76 Python files from the Hub package snapshot) is now in the package. Those scripts include publish helpers. They are not imported by `query_legal_records` and were not run.

Pipeline modules that collided on basename with newer local files are side by side under `hub_integrated/world_law_pipeline/`: `normalize.py`, `schema.py`, `archive_fetcher/cli.py`, `world/common.py`, `world/parquet_writer.py`, `world/run_batch.py`, and `world/run_batch_multi.py`. `shard_support.patch` and `text_preservation.patch` are stored under `hub_integrated/legal_scrapers/normalizers/` and were not applied. `country_laws_ir` was not replaced. Upload helpers were not copied. The older Hub `country_laws_ir` snapshot and the Madagascar and Venezuela stubs were not copied over the full local collectors.

`tests/unit/legal_scrapers/test_national_collectors.py` passed again after the catalog edit: 5 passed. `list_national_collectors()` returns 198 collectors. `load_collector_module("ad")` imports and does not run `main`.

## What is still gated

1. The American v3 export of snapshot `24cac8b72a91` finished and was uploaded. Do not start a second American writer for that pin.
2. Re-read the live source SHA the same day as any upload. Refuse the upload when it differs from the tree's `source_revision`, unless the go-ahead names the sampled pin. The American v3 upload kept sampled pin `24cac8b72a91` after the live source had moved.
3. A finished tree for a stable SHA can go to `justicedao/world_national_law` or `justicedao/world_municipal_law` with `upload_folder` only. `justicedao/american_municipal_law_norm` is now commit `d50ef57c6cd329c254a094a9396ec29528b920b8`.
4. After a destination SHA is recorded, leave `searchable` false and `revision` null until a go-ahead names that repo.
5. `LEGAL_QUERY_NORMALIZED` stays unset until that same kind of go-ahead.
6. Merging `ipfs_accelerate_py` to `eaaec0ac5` waits until `grok_cli_runner.py` can be merged without dropping the uncommitted supervisor runner.
7. Parser tokens still need a split test and a negative test before admission. This pass did not edit `structure.py`.
