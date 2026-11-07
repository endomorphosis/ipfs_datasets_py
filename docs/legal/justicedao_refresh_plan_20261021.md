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

HTML and sharded municipal packs run one at a time after the single-file wave. `/home` stayed near 30 GiB free because ZFS snapshots still hold the deleted world-card copies. Australia municipal was packed from live `df61dd884978` (54,755 laws), built locally, and published at `f53716087365`: 127,863 embedded vectors, 117,652 encoded and 10,211 reused. Germany municipal was packed from live `0c65e02ff1ae` (64,438 laws) and published at `a8bef6cefd66`: 170,608 embedded vectors, 90,582 encoded and 80,026 reused. Sweden municipal was packed from live `dd8e0431452e` (129,633 laws) and published at `9a14f20cf892`: 279,379 embedded vectors, 30,333 encoded and 249,046 reused. Brazil municipal was built from the four law shards and four article shards at live `4db83f75b0f6` and published at `df694b7d7665`: 94,459 laws, 687,110 articles, 781,569 embedded vectors, 293,021 encoded and 488,548 reused. The first upload stopped on a 429 at 3,367 of 3,759 files. The resume uploaded the remaining 391 files and removed 2 superseded Hub files. Korea municipal was built from the 24 law shards and 24 article shards at live `c82dcf06b735` and published at `0f5eb439926e`: 44,562 laws, 644,011 articles, 688,588 embedded vectors, 30,732 encoded and 657,856 reused. The first upload stopped when a presigned request expired at 2,954 of 3,089 files. The resume uploaded the remaining 135 files. The Hub tree matched the local release (3,143 files) with no extras. On 2026-11-05 batch 025 at live `d14ab8e3955e` was rebuilt as a delta and published at `bfd2370b1b44`: 45,807 laws, 661,868 articles, 707,690 embedded vectors, 19,102 encoded and 688,588 reused. The Hub tree matched the local release (3,230 files) with no extras. Do not rebuild that tip unless the source moves again. Italy municipal was packed from live `1b08aba59083` (24,580 laws; the 35 existing HTML files were unchanged and three new place files added 10,059 rows) and published at `2c7162faf6f4`: 101,398 embedded vectors, 43,129 encoded and 58,269 reused. The Hub tree matched the local release (444 files) with no extras. Belgium municipal was republished on 2026-11-06 at `ad68cae9b53a` from live tip `7d630b4fe625` plus the 206 besluiten restored from `df96e368` (16,139 rows). The index has 25,584 laws, 75,623 articles, and 102,892 embedded vectors, 1,032 encoded and 101,860 reused. All 206 decisions are present. 767 empty bodies were dropped. The Hub tree matched (441 files). Canada municipal was packed from live `49bdc79db81a` (55,276 laws; the 86 existing HTML files were unchanged and 23 new place files added 11,909 rows) and published at `2d52f6dee30f`: 71,174 embedded vectors, 16,812 encoded and 54,362 reused, 9 removed. Three superseded Hub files were deleted. Austria municipal was packed from live `011eb5303c1e` (17,011 laws; the 30 existing HTML files were unchanged at 13,385 rows and 8 new place files added 3,626 rows) and published at `e721c67acea5`: 199,910 embedded vectors, 160,677 encoded and 39,233 reused, 120,655 old document identities removed. Eleven superseded Hub files were deleted. Sweden municipal was packed from live `13d15864abe7` (139,861 laws; the 197 existing HTML files were unchanged at 129,633 rows and 16 new place files added 10,228 rows) and published at `472512f8e988`: 299,638 embedded vectors, 21,861 encoded and 277,777 reused, 1,602 removed. The Hub tree matched the local release (1,354 files) with no extras. Brazil municipal, Monaco, Vanuatu, and Saint Vincent parquet trees are unchanged since their indexed sources, so they were not rebuilt. Guernsey was published at `f2ff0eeea5cd` from source `1b137880c94b`: 5 laws, 0 articles (the articles file is empty), 5 embedded vectors. The Hub tree matched (65 files). Falkland Islands was published at `f1d8f736640f` from source `598ad7c2b6cc`: 29 laws, 235 articles, 353 embedded vectors. The Hub tree matched (66 files). Jersey was published at `9031c771f5dc` from source `445df60b7db4`: 263 laws, 4,452 articles, 4,774 embedded vectors. The Hub tree matched (90 files). The Isle of Man was published at `03f206bda695` from source `8644991c6bc6`: 194 instruments, 1,671 embedded vectors, none dropped. The Hub tree matched (72 files). Azerbaijan, Bolivia, the Dominican Republic, Sri Lanka, and Tunisia parquet trees match their indexed sources and were not rebuilt. This November 5 law-text pass is complete.

## GraphRAG screen, 2026-11-06

Read at 2026-11-06 05:52 UTC. 296 `endomorphosis/ipfs_*_laws` repos, 291 JusticeDAO IR repos, 36 candidates whose source tip was newer than the index or had no index. Identity is the parquet LFS oid at the live tip versus the IR manifest `source_revision`, then string-column hashes where the oid changed. A direct `build --source` of a Hub id reads only `data/laws.parquet` and `data/articles.parquet`, so an append file such as `laws_expand_20261105.parquet` has to be concatenated into a local pack first. No build was started by this pass while another reindex already held `cuda:0`. Nothing was committed or pushed.

| Repo | Live SHA | Indexed SHA | Law bytes |
| --- | --- | --- | --- |
| `ipfs_australia_laws` | `2ed53d930fb6` | `58732457a228` | 36,214 laws and 680,077 articles, same row counts, string text changed by the email redaction. Not rebuilt. |
| `ipfs_australia_state_laws` | `73c99a26be83` | none | No IR. Not a new query route. |
| `ipfs_azerbaijan_laws` | `9a3db83e5faf` | `206527c814b4` | Laws 9,951 to 10,006 and articles 10,863 to 13,042. String text changed. A parallel reindex is building this tip. |
| `ipfs_bahamas_laws` | `f2c2485fe7a7` | `2a905b47c991` | Archive pack added: 175 laws, 2,499 articles. Stays on endomorphosis. |
| `ipfs_belgium_regional_laws` | `6f7434e38d20` | none | No IR. Not a new query route. |
| `ipfs_bolivia_laws` | `72797f1ca9a9` | `779ab307a435` | Laws 8,448 to 8,493 and articles 61,407 to 62,256. String text changed. |
| `ipfs_brazil_municipal_laws` | `c76207b7ca9d` | `4db83f75b0f6` | Law bytes changed. New `laws-00005` has 5,063 rows and `articles-00005` has 29,894. Seven new HTML place files add 1,021 rows. Existing article shards grew. Existing law shards kept their row counts and their string hashes changed. Published at `8802289a379b` from source `724bad9e8f6f`. Parquet oids match packed `c76207b7ca9d`. |
| `ipfs_canada_state_laws` | `899e55e92f81` | none | No IR. Not a new query route. |
| `ipfs_dominicanrepublic_laws` | `fcbdd797b782` | `0e88091396de` | Laws 8,394 to 8,410 and articles 307,951 to 308,634. String text changed. The changed files are `data/laws.parquet` and `data/articles.parquet`. |
| `ipfs_el_salvador_laws` | `37fa317fdc7f` | `8199da865463` | 991 rows, same text, schema type changed. Not rebuilt. |
| `ipfs_finland_laws` | `aaeb5c70f28d` | `e2853063c76a` | Tip moved to a scraper overlay. Law parquet oids match `aa0027f18e08`. Pack is 106,682 laws and 396,651 articles, stamped `aaeb5c70f28d`. |
| `ipfs_germany_laws` | `af0902585755` | `3e4bc6dad4a0` | Repacked at the live tip: 15,010 laws and 232,360 articles. Includes Bavaria, Baden-Württemberg, Bremen, and gazette waves through wave 6 (+178 and +25). No id overlap. |
| `ipfs_iceland_laws` | `b6009086b25c` | `b4b6f9eefa6e` | Repacked at the live tip: 3,310 laws and 69,609 articles. The new shard adds 45,841 regulation articles. No id overlap and no empty text. |
| `ipfs_iraq_laws` | `0c7c96258a3f` | `0c7c96258a3f` | Same SHA. |
| `ipfs_jordan_municipal_laws` | `1a7f58722d4e` | `2e5757f1dbae` | 62 laws and 1,205 articles, same text. Not rebuilt. |
| `ipfs_latvia_district_laws` | `5d2b724043d2` | none | No IR. Not a new query route. |
| `ipfs_mozambique_municipal_laws` | `6014295ae104` | `dacf644616ef` | 10 laws and 479 articles, same text. Not rebuilt. |
| `ipfs_namibia_municipal_laws` | `2bbc27a9697f` | `0b87f08f1d75` | 3 laws and 68 articles, same text. Not rebuilt. |
| `ipfs_north_korea_laws` | `d2b031099a58` | `59ceccb763e1` | 84 laws, same text. Not a publish path. |
| `ipfs_palestine_municipal_laws` | `986bfbf9196d` | `685744c3d72a` | 63 laws and 1,116 articles, same text. Not rebuilt. |
| `ipfs_san_marino_laws` | `77e8badaa3b9` | `93dbd6ba8195` | 380 laws, same text. Not rebuilt. |
| `ipfs_saudi_arabia_municipal_laws` | `9362321157c6` | `4d574a961c82` | 192 laws, same text. Not rebuilt. |
| `ipfs_slovakia_regional_laws` | `45045989b0d3` | none | No IR. Not a new query route. |
| `ipfs_south_africa_provincial_laws` | `390380e0203b` | `1368446176bc` | Pack 2 adds 2 laws and 34 articles. Not a query route. |
| `ipfs_srilanka_laws` | `915ac7d46e9a` | `9c6c2083e029` | Laws 8,459 to 8,491 and articles 11,104 to 11,144. String text changed. Queued on the parallel reindex. |
| `ipfs_suriname_laws` | `26d6fdc191c4` | `2d249028ef2e` | Archive pack added: 98 laws, 1,878 articles. Stays on endomorphosis. |
| `ipfs_switzerland_municipal_laws` | `5165f4d4cbb6` | `4f6e47ffa159` | Parquet oids unchanged. Scraper files only. Not rebuilt. |
| `ipfs_thailand_laws` | `c274c7d4d67b` | `c274c7d4d67b` | Same SHA. |
| `ipfs_trinidad_laws` | `6f1d8cba4009` | `9bd47e8883c1` | Archive pack added: 69 laws, 1,411 articles. Stays on endomorphosis. |
| `ipfs_trinidad_and_tobago_laws` | `d6be2336df78` | `a611898a3d12` | 267 laws, same text. Not rebuilt. |
| `ipfs_tunisia_laws` | `92049a8be712` | `9676c8be515a` | Laws 9,496 to 9,530 and articles 98,185 to 98,502. String text changed. Queued on the parallel reindex. |
| `ipfs_tunisia_municipal_laws` | `97396cdcdd92` | `bbaf4ecfc2af` | All 16 shards kept their row counts and string hashes. Not rebuilt. |
| `ipfs_united_states_county_laws` | `1a2e64d808e9` | `a1ecb5c93bf6` | `articles-00017.parquet` adds 1 row. `laws-00017.parquet` oid changed. Not a new route, and `american_municipal_law_norm` stays at `df0c0c405bf5`. |
| `ipfs_united_states_state_laws` | `a41ca6d98343` | none | No IR. Not a new query route. |
| `ipfs_vanuatu_laws` | `2cd7af3c80b1` | `88abba620d3d` | Laws 399 to 708 and articles 1,107 to 2,509. String text changed. |
| `ipfs_zimbabwe_municipal_laws` | `a3765d88bf10` | `3b68fad4d30c` | 11 laws and 122 articles, same text. Not rebuilt. |

Vanuatu's index was already rebuilt from `2cd7af3c80b1` by a reindex that was running in parallel: local release 708 laws, 2,509 articles, 24,357 embedded vectors, Hub commit `b41ca56edb03`. This pass did not start a second Vanuatu build.

Cards re-read the same morning, and not turned into new GraphRAG repos: `world_national_law` `c45b303c4cb5`, `world_municipal_law` `d69a0c084528`, `world_caselaw` `8f23842807d3`. `world_courts` and `american_municipal_law` stay report-only. `justicedao/world_national_law_norm` is `2db89b2d08da` ("Add Taiwan national atoms recovered from article headings", 2026-11-06 05:40 UTC), which is newer than the earlier label upload `13f2fc765aed`. That norm repo stays unsearchable and is not uploaded again from the older 2,153-part tree.

Belgium municipal stays at `ad68cae9b53a`. Australia national is not rebuilt. Brazil municipal was packed and published later in this section. The Finland, Germany, and Iceland packs are under `/storage/hf_cache/country-laws-ir/expand-packs/`. Each `pack_meta.json` `source_revision` is the live tip above. `article_count` was promoted from int32 to int64 where the append file differed. No ids overlapped the base file, and none of the append rows had empty text.

A parallel reindex then published eight indexes. Local manifests are `embedded`, `thenlper/gte-small`, dimension 384, `vector_rows` equal `corpus_rows`, and `n_missing` 0.

| Repo | Source SHA | Hub revision | Corpus rows |
| --- | --- | --- | --- |
| `justicedao/ipfs_monaco_laws_ir` | `f77015ddec51` | `3fd75e2356e2` | 1,755 |
| `justicedao/ipfs_saint_vincent_grenadines_laws_ir` | `f2be97656205` | `265f1dd1b4d5` | 6,170 |
| `justicedao/ipfs_iraq_laws_ir` | `0c7c96258a3f` | `7c1175a264d3` | 7,054 |
| `justicedao/ipfs_vanuatu_laws_ir` | `2cd7af3c80b1` | `b41ca56edb03` | 24,357 |
| `justicedao/ipfs_azerbaijan_laws_ir` | `9a3db83e5faf` | `29bf76b652af` | 34,727 |
| `justicedao/ipfs_bolivia_laws_ir` | `72797f1ca9a9` | `b764db2ef379` | 77,382 |
| `justicedao/ipfs_srilanka_laws_ir` | `915ac7d46e9a` | `11f35e691f97` | 101,130 |
| `justicedao/ipfs_tunisia_laws_ir` | `92049a8be712` | `92cc571a7764` | 113,885 |

That uploader does not delete Hub files that are absent from the new release. The extra files were deleted afterward. Each of the eight Hub trees then matched its local release, including the old Vanuatu, Sri Lanka, and Tunisia search shards.

Finland was built from the local pack at `aaeb5c70f28d` and published with `upload_folder`. `justicedao/ipfs_finland_laws_ir` is `b62b9fb005ac` after the extra-file delete. The Hub manifest is `embedded`, `thenlper/gte-small`, dimension 384, 508,355 corpus rows, 508,355 vectors, `n_missing` 0. The first upload commit was `68e02bc3f248`.

Germany was published with `upload_folder`. `justicedao/ipfs_germany_laws_ir` is `8b6d89490080` after deleting 204 files that were not in the release. The first upload commit was `9c301d3df37c`. The Hub manifest is `embedded`, `thenlper/gte-small`, dimension 384, 303,034 corpus rows, 303,034 vectors, `n_missing` 0, source `af0902585755`. Iceland was published with `upload_folder`. `justicedao/ipfs_iceland_laws_ir` is `4198736e5361` after deleting 101 files that were not in the release. The first upload commit was `75f208731199`. The Hub manifest is `embedded`, `thenlper/gte-small`, dimension 384, 72,740 corpus rows, 72,740 vectors, `n_missing` 0, source `b6009086b25c`. The Dominican Republic was published with `upload_folder`. `justicedao/ipfs_dominicanrepublic_laws_ir` is `0a00358e84eb` after deleting 411 files that were not in the release. The first upload commit was `a8d42d22af20`. The Hub manifest is `embedded`, `thenlper/gte-small`, dimension 384, 320,566 corpus rows, 320,566 vectors, `n_missing` 0, source `31036f2d505e`. The law parquet matches the hashed tip `fcbdd797b782`.

Brazil municipal was packed at `c76207b7ca9d`: 103,827 laws and 768,310 articles. The five law shards and five article shards had no shared ids. The 41 HTML municipality files were not in those shards, so their 4,305 documents were added as laws. Scraper fixtures were left out. The build kept 886,629 documents, dropped 62, reused 482,529 vectors, and encoded 404,100. The live tip then moved to `724bad9e8f6f` with the same 59 parquet oids, so the release was stamped with that revision and was not rebuilt. It was published with `upload_folder`. `justicedao/ipfs_brazil_municipal_laws_ir` is `8802289a379b` after deleting 720 files that were not in the release. The first upload commit was `5e1f96992ba5`. The Hub manifest is `embedded`, `thenlper/gte-small`, dimension 384, 886,629 corpus rows, 886,629 vectors, `n_missing` 0, source `724bad9e8f6f`. The local tree and the Hub tree both have 4,291 files.

## GraphRAG screen, 2026-11-07

`ipfs_datasets_py` origin/main was already `4b8ed13e8`. The first-level submodule checkouts stay on the commits that pin records, because those worktrees are dirty. Hub code tips moved: `endomorphosis/legal_scrapers` `752ba7c01080`, `endomorphosis/world_law_pipeline` `26004b9f7963`, and `justicedao/world_law_scrapers` `6b0cef287334`. The pipeline county-lane files were vendored with the sandbox path rewrite. New caselaw collectors and the q4 normalizer bundle were copied under `hub_integrated`. The `scrapers_and_normalizers` overlay did not change existing files and was not copied again. No new query route was added.

The same-day law screen is `/tmp/grok-barberb/jdq-freshness/graphrag_screen_20261107.json`. Most newer tips are scraper overlays whose commit says `data/* untouched`. Those are not rebuilt. Confirmed additive law files with an existing index, and not a new route, include Germany, Iceland, Greece, Japan, Ukraine, Bulgaria, Israel, Montenegro, Spain, South Africa, Taiwan, Kyrgyzstan, Luxembourg, Guam, Armenia, Georgia, Canada, Nigeria, Romania, and Brazil. Missing indexes for territories and `united_states_county` stay off new query routes. World cards and `world_national_law_norm` stay unsearchable.

Germany was repacked at live `ef5a29947de3`. The previous ten parquet files were unchanged. Six added files contribute 517 laws and 1,088 articles, with no id overlap and no empty text. The pack is 15,527 laws and 233,448 articles. It was published with `upload_folder`. `justicedao/ipfs_germany_laws_ir` is `452729c915ee`. The Hub tree matched the local 1,774 files, so no extra shards were deleted. The Hub manifest is `embedded`, `thenlper/gte-small`, dimension 384, 343,701 corpus rows, 343,701 vectors, `n_missing` 0, source `ef5a29947de3`. 298,765 vectors were reused and 44,936 were encoded.

Romania is packed and not yet built. Live `endomorphosis/ipfs_romania_laws` was still `5b0f28e047a9`. `data/laws.parquet` and `data/articles.parquet` match indexed `5828122eb9a5`. The only added parquet is `data/laws_expand_20261105.parquet` (4 laws, no empty id, no empty text, no id overlap). The local pack is `/storage/hf_cache/country-laws-ir/expand-packs/romania`: 81,876 laws and 23,984 articles. Romania is already `indexable` in the country catalog, so this refresh does not add a query route. The GraphRAG build waits until `cuda:0` is free of the caselaw `append_opinion_vectors.py` job.

A same-day parquet oid pass is `/tmp/grok-barberb/jdq-freshness/additive_identity_20261107.json`. Every listed tip still matched the screen. Base parquet oids were unchanged and new parquet files were added for Iceland (16), Taiwan (1), Spain (2), South Africa (3), Kyrgyzstan (6), Canada (9), Nigeria (2), Bulgaria (2), Guam (4), Armenia (8), Georgia (8), Israel (2), Luxembourg (2), Montenegro (1), Japan (4), Japan municipal (2), Greece (1), Ukraine (14), Brazil national (1), and Czechia (2). Chile, China, and Kenya have the same parquet oids as their indexes, so those scraper overlays are not rebuilt. Austria municipal has no indexed source revision on that screen and its live tree is HTML shards, so it is not packed. Greece and Ukraine stay behind the smaller appends. A Hub-id build would miss every added file, so each of these needs a local pack before its build.
