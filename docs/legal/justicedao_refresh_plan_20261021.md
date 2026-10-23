# JusticeDAO refresh plan, 2026-10-21

Raw law stays on `endomorphosis`. Normalized retrieval stays on `justicedao`. A query names the jurisdiction it wants. It does not read the caller IP, locale, or country, and it does not read `endomorphosis`.

This plan is the 2026-10-21 review, read at 01:03 UTC. The 2026-10-17 plan remains the contract for export gates and excluded slugs. The 2026-10-19 plan's SHA table is historical. This pass does not upload a norm tree and does not start an export.

## Git pull

`external/ipfs_datasets` fast-forwarded `629169ed2..5beb7f4f7` (`5beb7f4f7f03307f37684908cbb85ae977fc08b6`). Those 18 commits are LegalIR source-coordinate and programme delivery. They add no scraper, normalizer, parser, or `query_legal_records` files. The dirty legal worktree did not overlap the incoming paths, so the fast-forward kept the uncommitted scrapers and `hub_integrated`. Nothing was committed. The parent `lift_coding` gitlink was not moved.

Direct submodules were fetched one level, with submodule recursion off.

| Checkout | Result |
| --- | --- |
| `ipfs_datasets` | Fast-forward landed. `HEAD` equals `origin/main` (`0` behind, `0` ahead). |
| `ipfs_kit_py` and `.tools/ipfs_kit_py` | Already at `origin/main` `40c98c71b`. |
| CEC libraries, multimedia, common-crawl | Already at their `origin/main` tips. They were not rewound. |
| `ipfs_accelerate_py` | Stayed at `ff69c6dec`. `origin/main` is `e227152f7`, 73 commits ahead. The dirty file `agent_supervisor/runtime/grok_cli_runner.py` is also changed on that tip, so the checkout was not merged. |
| Parent `lift_coding` | Stayed at `4586d7e1068c`. `origin/main` is `b4cc72cafc`, 69 commits ahead. The worktree is dirty on submodule gitlinks, so that parent history was not merged. |

## Endomorphosis review

Live tips re-read on 2026-10-21 00:57 UTC from `repo_info`.

| Repo | SHA | Last modified | Justicedao destination |
| --- | --- | --- | --- |
| `endomorphosis/world_national_law` | `84b7b7d6b13856fa3352f6bf83532cdf91f85262` | 2026-10-21 00:42:07Z | absent |
| `endomorphosis/world_municipal_law` | `71c1eb24c6f1fe3f7fdedede3a2fddfbcc5a75a4` | 2026-10-21 00:42:02Z | absent |
| `endomorphosis/american_municipal_law` | `38b7c6321c2dcaef2dabb85d4d5e5ca45db2b1b2` | 2026-10-21 00:45:38Z | norm repo present, see below |
| `endomorphosis/legal_scrapers` | `8295eebd6fb75202e89fdeefe423bd3ba6bf9cc6` | 2026-10-18 21:28:32Z | source, already vendored |
| `endomorphosis/world_law_pipeline` | `da0447c4adeb6a134cd539a8a9d23c9d80fe59c1` | 2026-10-20 21:41:34Z | source, vendored below |

`justicedao/american_municipal_law_norm` is `df0c0c405bf59cb948d1269dea29767a4712fb81` (2026-10-19 14:17:23Z), normalizer `american-municipal-html/v4+legal-record/v1`, source snapshot `24cac8b72a91`, 17,109,461 rows kept and 801 `not_atomic` drops. `justicedao_release_pins.json` marks that repo searchable at `df0c0c40`. `justicedao/american_municipal_law` stays blocked at `19009d5d2c66`. Do not upload another American tree over `df0c0c40`.

`world_law_scanned_pdfs` stays on endomorphosis. Archived, non-official, and `source_official=false` rows stay on endomorphosis. Belgium, Portugal, Lithuania, and Ghana national stay unpublished as query routes. `egypt_governorate`, `south_africa_provincial`, and `wallis_futuna` stay unpublished.

LawMa and LawMaToo still have no Python files. Their weights were not downloaded. justicedao has no models. `justicedao/legal_scrapers` and `justicedao/world_law_pipeline` are absent. `justicedao/world_law_scrapers` is present at `1b6274b536baf8cd0657f6a04694760f96822836` (2026-10-16 02:44:01Z) and is vendored below.

## Exports

The American v4 writer that was on pids 1237799 and 1237811 has finished. The log ends with `WROTE american_municipal_law_v4` for pin `24cac8b72a91`, 17,109,461 rows, the same counts as Hub commit `df0c0c40`. The local tree is 19 GiB at `norm-export/24cac8b72a91/american_municipal_law_v4`. The log still records `SOURCE_MOVED` against the then-live source `d2a4c3b7`. The live American source is now `38b7c632`. Do not upload this tree again, and do not start another American writer.

No municipal or national export is running. `/home` has 59 GiB free of 782 GiB (93 percent used). A world export of the current cards would not fit beside a 40 GiB reserve, and both cards moved again at 00:42 UTC.

Local trees that must not be uploaded as the current card:

| Tree | Why it stays local |
| --- | --- |
| `norm-export/9544a706bdc5/world_national_law` | Live national commit is `84b7b7d6`, not `9544a706`. |
| `norm-export/0c715ba7a917/...` | Live municipal commit is `71c1eb24`, not `0c715ba7`. |
| `norm-export/24cac8b72a91/american_municipal_law_v4` and `110a2c27131d` | American norm is already `df0c0c40` for pin `24cac8b72a91`. The live American source is `38b7c632`. |

`export_norm --upload` still raises `ExportUploadBlocked`. An upload uses `upload_folder` only after a finished local tree, a same-day source SHA that still equals the tree's `source_revision`, a destination that does not already exist, and a named repo. World destinations are absent, and the finished local trees are not the live SHAs, so they are not uploaded.

## Query from anywhere

`query_legal_records` checks `LEGAL_QUERY_NORMALIZED` before jurisdiction resolution. The flag now defaults on: an unset variable is treated as `1`, and any other value raises `LegalQueryDisabled`. This pass did not change that default. The requested jurisdiction selects the repo. An unknown jurisdiction returns an empty `LegalQueryResult` and no US Code rows. There is no `CLIENT_COUNTRY` and no geo-IP branch. The reader does not fall back to endomorphosis.

`justicedao/american_municipal_law_norm` is readable at `df0c0c40`, so a US ordinance request can open that pin. `world_national_law` and `world_municipal_law` stay `searchable` false with `revision` null, so a national or municipal request uses the per-country `justicedao/ipfs_*_laws_ir` repo when the caller does not pass a gap status. The absent world cards are not opened. `representation` is a query view and is not part of `query_id`.

`query_legal_records` does not import `hub_integrated`. This pass did not edit that module, so the client-location tests were not re-run.

## Package integration

`legal_scrapers` was still `8295eebd`, so that vendor was left as it is. The pipeline tip moved from `e5f232368` to `da0447c4` (24 added files, 18 changed, 0 removed). Twenty-seven Python and Markdown sources were copied into `hub_integrated/world_law_pipeline/` and `compileall` exited 0. Shells, probe scripts, `.gitattributes`, and the 117,689,955-byte `state/doc_overrides.json` were not copied.

`justicedao/world_law_scrapers` was not in the package. 1,820 Python and Markdown files were written under `hub_integrated/justicedao_world_law_scrapers/` (1,799 of them Python). `compileall` on that tree exited 0. Left out: 6 probe scripts, 4 launcher scripts, and 15 files that call `upload_folder`, `upload_file`, or `create_repo`, including the nested `country_laws_ir/upload.py`. No token value was copied. Importing `hub_integrated` does not import these collectors.

The live `country_laws_ir` tree was not edited this pass. On disk now, `structure.py` is 90,599 bytes and `normalize.py` is 49,780 bytes. Hub text-preservation copies stay beside that tree and were not applied.

`hub_integrated/__init__.py` records `8295eebd`, `da0447c4`, and `1b6274b5`.

## Update screen, 2026-10-21 03:32 UTC

`list_datasets` returned 287 endomorphosis datasets and 311 justicedao datasets. Of the `ipfs_*_laws` sources, 238 have a justicedao `ipfs_*_laws_ir` commit at least as new as the source commit. Thirty-one source commits are newer than that index. Two sources have no index.

`justicedao/world_national_law_norm` exists at `3718ed83` (2026-10-20 21:53:30Z). Its manifest is `country-source-admit/v1` for 216 country corpora. It is not the HTML world card, and its README says it is not a query pin. Belgium, Portugal, Lithuania, Ghana, and Denmark are outside it. `justicedao/world_national_law` and `justicedao/world_municipal_law` are still absent, and `justicedao/world_municipal_law_norm` is absent.

Live card tips at 03:32 UTC were still the 02:35 UTC drops: national `49f737ac` (15 places) and municipal `863c3484` (556 places in three commits). American municipal was still `9a528a60` (2026-10-21 03:11:45Z), an HTML flush of new places. The published American norm remains `df0c0c40` for pin `24cac8b72a91`. No export was started. Those three sources were still receiving new commits, so a multi-hour export would finish on a commit that is no longer the tip.

Commit titles for the 31 newer country sources:

| Keep the current index | Newer source that the index does not contain |
| --- | --- |
| ZSTD recompress, rows preserved: North Korea, San Marino, Trinidad and Tobago, Moldova, and the municipal sets for Zimbabwe, Saudi Arabia, Jordan, Palestine, Tunisia, and the Netherlands | Germany: +19 laws / +240 articles |
| Slovakia municipal: manifest hash regenerated from the files already in the repo | Australia municipal: tranche 4 HTML parquet |
| Switzerland municipal and Sweden municipal: scraper or coverage files | Azerbaijan, Bolivia, and Sri Lanka: `laws.parquet` and `articles.parquet` in the same minute as the README tip |
| Tunisia and Serbia tips are README commits | Cambodia: article heading-line fix |
| Ghana's tip is a README restore. An earlier same-day append added acts. Ghana stays out of the query routes | Korea municipal: placeholder-body tags |
| | Mauritius, Kuwait, Guinea-Bissau, and Egypt: Africa/MENA batch 2 row increases |
| | India +92 instruments, El Salvador +15 decrees, China +19 instruments |
| | Iraq: article-count fix on 9 laws |

No index exists yet for French Polynesia (`5a4e9931`, 3,103 laws / 30,819 articles, 2026-10-17) or Taiwan municipal (`d06f8a44`, Taichung, 3,584 laws / 38,457 articles, 2026-10-17).

`world_law_scanned_pdfs` and `world_law_scanned_text` stayed on endomorphosis. `legal_scrapers` was still `8295eebd`.

## What is still gated

1. Do not upload `9544a706`, `0c715ba7`, `24cac8b72a91`, or `110a2c27131d` as the current world or American card. Do not upload over `df0c0c40`.
2. Do not start an export of `84b7b7d6` or `71c1eb24` on this disk. A later export needs a go-ahead that accepts a moving source, or a same-day re-read that still matches, and enough free space to keep about 40 GiB in reserve.
3. Leave `world_national_law` and `world_municipal_law` `searchable` false and `revision` null until a go-ahead names that repo.
4. Merging `ipfs_accelerate_py` waits until `grok_cli_runner.py` can be merged without dropping the uncommitted supervisor runner.
5. Applying a Hub text-preservation tree onto `country_laws_ir` waits for a named go-ahead and tests.

## GraphRAG wave, 2026-10-21 03:49 UTC

A manifest `source_revision` screen, not the commit clock, is the rebuild list. Of 45 `ipfs_*_municipal_laws` sources, 26 indexes already store the live source SHA and are `vector.status` embedded. The other 19 are stale or missing. Commit titles then split those 19 into law-text changes and SHA-only changes.

Started at 03:49 UTC, mode `auto`, upload on, two workers, `IR_RSS_ABORT_GIB=40`. Every repo in this wave has exactly one `data/laws.parquet` and one `data/articles.parquet`. Log: `/tmp/grok-barberb/jdq-freshness/cid-logs/graphrag_reindex_20261021.log`. Kuwait loaded 212 laws / 1,274 articles and Egypt loaded 454 laws / 1,933 articles, matching the Africa/MENA batch 2 counts. The queue after them is Mauritius, Iraq, Cambodia, Guinea-Bissau, China, El Salvador, Azerbaijan, French Polynesia, Taiwan municipal, India, Bolivia, Sri Lanka, and Germany. Sri Lanka and Germany take two slots, so each runs alone. French Polynesia and Taiwan municipal had no index. Ghana is not in the queue.

Not in this wave, because the Hub reader publishes whatever single `data/laws.parquet` it finds and would stamp the new SHA over missing text:

- Australia municipal, Germany municipal, and Sweden municipal are HTML parquet. Australia tranche 4 is new. Germany municipal and Sweden municipal each have HTML parquet commits newer than the indexed source revision (the indexed SHA is older than the newest 40 commits; 11 and 19 of those commits are HTML parquet).
- Brazil municipal is four `laws-*.parquet` shards. Pack 00004 adds 30,444 laws and 262,575 articles. Korea municipal is 24 shards. Batch 024 adds 2,000 laws and 28,667 articles. Later Korea commits retag placeholder bodies and do not change title or text.
- Denmark municipal, Finland municipal, Slovakia municipal, and Switzerland municipal moved only by scraper code or a manifest hash. Estonia municipal re-keyed 785 article ids and left the text unchanged. ZSTD recompress commits stay on the current index.

`endomorphosis/world_municipal_law` at `cf76617c9519` (2026-10-21 03:43:20Z) has 109 country folders of `world_law/data/{ISO}/*_html.parquet`. It was still receiving drops: 586 places at 03:41 UTC and 37 places at 03:43 UTC. A full place count was not taken. Thirty-two folders match a country municipal repo by slug. New Zealand, Saudi Arabia, South Africa, and Czechia are the same repos under a different slug spelling, and the United States is `justicedao/american_municipal_law_norm`. That leaves HTML places for about 72 countries that have no `ipfs_*_municipal_laws` repo. Andorra, Denmark, Finland, Luxembourg, Malta, Mauritius, Namibia, Sweden, and Switzerland have a country municipal repo and no folder on this world card. Those 72 countries were not projected into new GraphRAG repos. The card was still moving, and the country-index builder does not read it. GB places on that card stay off `ipfs_uk_laws_ir`. Syria stays archive-only. Ghana stays off the query routes.

### Progress, 2026-10-21 04:22 UTC

Published and checked against the local release. Each index is `thenlper/gte-small`, 384-d, `vector.status` embedded, `vector_rows` equal to `corpus_rows`, `n_missing` 0. Hub files that were not in the new release were deleted so a parquet glob cannot mix an older shard. The tip below is that cleanup commit when one was needed.

| Repo | Tip | Source revision |
| --- | --- | --- |
| `justicedao/ipfs_kuwait_laws_ir` | `be76ebf6c2f1` | `bae7926db09f` |
| `justicedao/ipfs_egypt_laws_ir` | `5ecb9f4cf265` | `36e3b27e8640` |
| `justicedao/ipfs_mauritius_laws_ir` | `dc15b62c05e1` | `80f8c6317588` |
| `justicedao/ipfs_iraq_laws_ir` | `f6dd61ad98fd` | `e3c7d6d278c4` |
| `justicedao/ipfs_cambodia_laws_ir` | `91e4e0cea4a5` | `4b1cc6dfdab3` |
| `justicedao/ipfs_guineabissau_laws_ir` | `e9b6461ea8af` | `c06c89d0aab0` |
| `justicedao/ipfs_china_laws_ir` | `a3421351e04d` | `f18d968eb082` |
| `justicedao/ipfs_elsalvador_laws_ir` | `b0caf2192016` | `d43dfdaedb1e` |
| `justicedao/ipfs_azerbaijan_laws_ir` | `4703d71c2a77` | `957569f69a9a` |
| `justicedao/ipfs_french_polynesia_laws_ir` | `9e37df15fea5` | `5a4e9931ed78` |
| `justicedao/ipfs_taiwan_municipal_laws_ir` | `3ffe7d625b38` | `d06f8a4487cc` |
| `justicedao/ipfs_india_laws_ir` | `fab7ab746167` | `829e377049c8` |
| `justicedao/ipfs_bolivia_laws_ir` | `e31e7d6cf90e` | `c7521d1c306d` |
| `justicedao/ipfs_srilanka_laws_ir` | `5dbf1ce901d1` | `6170c1d22027` |
| `justicedao/ipfs_germany_laws_ir` | `ce72b88501fc` | `d7b6f285b3cb` |

French Polynesia is new. The local build has 3,102 laws, 30,816 articles, and 33,919 embedded vectors. The Xet large-folder upload aborted. A fresh process published the tree with `upload_folder` and `HF_HUB_DISABLE_XET=1`. The ignore pattern `*token*` skipped `country_laws_ir/tokenize.py`; that file was committed on its own. Live `endomorphosis/ipfs_french_polynesia_laws` was still `5a4e9931ed78`. China was recovered the same way earlier and already matched file-for-file.

Taiwan municipal is new. The pool upload succeeded at `1c1513b4f3e9` (3,540 laws, 38,453 articles, 42,037 embedded vectors, source `d06f8a4487cc`). The same ignore pattern left out `tokenize.py`, added at `3ffe7d625b38`. The Hub tree matches the local release. There were no older shards to delete.

India's pool upload aborted on the Xet path at 04:30 UTC. The local release was already embedded: 1,072 laws, 44,095 articles, 45,501 vectors, 39,443 reused and 6,058 encoded, source `829e377049c8`. A fresh process published it with `upload_folder` and `HF_HUB_DISABLE_XET=1`, then added `tokenize.py` and deleted 60 superseded Hub files. The tip is `fab7ab746167`. Live `endomorphosis/ipfs_india_laws` was still `829e377049c8`.

Bolivia's pool upload aborted on the Xet path at 04:46 UTC. The local release was already embedded: 8,296 laws, 57,513 articles, 70,664 vectors, 69,691 reused and 973 encoded, source `c7521d1c306d`. A fresh process published it with `upload_folder` and `HF_HUB_DISABLE_XET=1`, then added `tokenize.py` and deleted 33 superseded Hub files. The tip is `e31e7d6cf90e`. Live `endomorphosis/ipfs_bolivia_laws` was still `c7521d1c306d`.

Sri Lanka's pool upload succeeded at 05:28 UTC (`9396abfd9174`). The local release has 8,438 laws, 11,558 articles, and 90,452 embedded vectors (73,663 reused, 16,789 encoded), source `6170c1d22027`. Live `endomorphosis/ipfs_srilanka_laws` was still that revision. The Hub tree had 369 older files; those were deleted at `5dbf1ce901d1`, and the tree then matched the local release.

Germany's pool upload aborted on the Xet path at 06:22 UTC. The local release was already embedded: 12,345 laws, 182,253 articles, 194,668 vectors, 171,370 reused and 23,298 encoded, source `d7b6f285b3cb`. A fresh process published it with `upload_folder` and `HF_HUB_DISABLE_XET=1`, then added `tokenize.py` and deleted 314 superseded Hub files. The tip is `ce72b88501fc`. Live `endomorphosis/ipfs_germany_laws` was still `d7b6f285b3cb`. The pool then exited 1 because five Xet uploads had aborted. All five were recovered: China, French Polynesia, India, Bolivia, and Germany. Do not rebuild these fifteen repos. Do not pass `--force`.

HTML and sharded municipal packs run one at a time after the single-file wave. `/home` stayed near 30 GiB free because ZFS snapshots still hold the deleted world-card copies. Australia municipal was packed from live `df61dd884978` (54,755 laws), built locally, and published at `f53716087365`: 127,863 embedded vectors, 117,652 encoded and 10,211 reused. Germany municipal was packed from live `0c65e02ff1ae` (64,438 laws) and published at `a8bef6cefd66`: 170,608 embedded vectors, 90,582 encoded and 80,026 reused. Sweden municipal was packed from live `dd8e0431452e` (129,633 laws) and published at `9a14f20cf892`: 279,379 embedded vectors, 30,333 encoded and 249,046 reused. Brazil municipal was built from the four law shards and four article shards at live `4db83f75b0f6` and published at `df694b7d7665`: 94,459 laws, 687,110 articles, 781,569 embedded vectors, 293,021 encoded and 488,548 reused. The first upload stopped on a 429 at 3,367 of 3,759 files. The resume uploaded the remaining 391 files and removed 2 superseded Hub files. Korea municipal was built from the 24 law shards and 24 article shards at live `c82dcf06b735` and published at `0f5eb439926e`: 44,562 laws, 644,011 articles, 688,588 embedded vectors, 30,732 encoded and 657,856 reused. The first upload stopped when a presigned request expired at 2,954 of 3,089 files. The resume uploaded the remaining 135 files. The Hub tree matched the local release (3,143 files) with no extras. This municipal wave is complete. Do not rebuild these repos.
