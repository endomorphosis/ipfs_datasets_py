# WORLD COVERAGE AUDIT

Generated 2026-10-10 (PT) by a read-only audit. Nothing was uploaded and no Hub repo was modified. Hub data came from public parquet footers (HTTP range reads, no dataset downloads) and public repo file listings; no token was used.

Machine-readable version: `world_coverage_audit.json` (same directory).

## 0. Headline

- Universe: 195 sovereign states (193 UN members + Holy See + Palestine). Standing skips: US, IS.
- Hub: **240** `endomorphosis/ipfs_*_laws` datasets (same 235 unique no-underscore slugs as `world_gap.json`; the difference is duplicate underscore-named datasets, see 1d).
- **Missing: 2 of 195**: `US` (standing skip) and `VA` Holy See. Only **1 real gap (VA)** once skips are removed. Iceland has a dataset (917 laws) but is a standing skip.
- **Thin by the stated rule (laws<50 or articles==0): 3**: ER, KW, KP (all 0 articles, 84-102 laws). No dataset has fewer than 50 laws (smallest: SD 56, SZ 56, AF 62).
- Breadth is essentially done; the gap is **depth**. Tier counts across the 193 covered countries: {"A_thin": 3, "B_stub_50_249": 72, "D_substantial_1000plus": 73, "C_small_250_999": 45}. 72 countries sit at 50-249 laws, which is stub-level for a national legal system. README 'Coverage' fields self-declare: {"snapshot/other": 60, "incomplete": 108, "unstated": 9, "complete": 16}.
- Non-country datasets: 41 (1 supranational, 2 non-UN states, 13 territories, 25 municipal/subnational).
- A common **normalized** schema exists and is published (`justicedao/ipfs_<slug>_laws_ir`), but the **raw** `ipfs_*_laws` layer has 13 laws column-set variants and dtype drift. The normalizer is NOT in `endomorphosis/legal_scrapers`.

## 1. Country gap analysis

### (a) Countries with NO dataset

| ISO | Country | Note |
|---|---|---|
| US | United States | standing skip (USA) |
| VA | Vatican City (observer) | NO DATASET - real gap |

### (b) Thin datasets (laws < 50 OR articles == 0; counts from parquet footers)

| ISO | Country | Dataset | Laws | Articles | Reasons | README laws/articles |
|---|---|---|---:|---:|---|---|
| ER | Eritrea | endomorphosis/ipfs_eritrea_laws | 102 | 0 | articles==0 | 102/None |
| KW | Kuwait | endomorphosis/ipfs_kuwait_laws | 93 | 0 | articles==0 | 93/0 |
| KP | North Korea | endomorphosis/ipfs_northkorea_laws | 84 | 0 | articles==0 | 84/None |

Informational: 18 more datasets have >=50 laws but articles/laws < 3 (weak article splitting): AD(218299/16322), AZ(9362/9750), CZ(41340/15091), FJ(434/254), GR(6988/4656), IT(203128/31443), LB(108/56), MW(5361/4712), MV(2535/1678), FM(468/16), MC(862/438), ME(700/1879), OM(1679/2069), RO(81872/23984), LK(8116/10707), SD(56/69), TH(283/78), ZM(5442/10936).

#### Informational tier B: stub-level (50 <= laws < 250), 72 countries, smallest first

| ISO | Country | Laws | Articles |
|---|---|---:|---:|
| SZ | Eswatini | 56 | 2385 |
| SD | Sudan | 56 | 69 |
| AF | Afghanistan | 62 | 4905 |
| LY | Libya | 69 | 692 |
| CI | Cote d'Ivoire | 71 | 3771 |
| IQ | Iraq | 76 | 335 |
| SO | Somalia | 77 | 1833 |
| BI | Burundi | 79 | 2418 |
| SS | South Sudan | 80 | 535 |
| GA | Gabon | 81 | 11599 |
| GQ | Equatorial Guinea | 86 | 2041 |
| VU | Vanuatu | 89 | 1062 |
| LS | Lesotho | 90 | 6718 |
| CF | Central African Republic | 93 | 3472 |
| GM | Gambia | 94 | 4517 |
| SR | Suriname | 94 | 2164 |
| BY | Belarus | 98 | 7335 |
| TD | Chad | 99 | 19425 |
| DZ | Algeria | 100 | 492 |
| GH | Ghana | 101 | 8572 |
| TZ | Tanzania | 101 | 6340 |
| BJ | Benin | 102 | 1900 |
| NE | Niger | 102 | 17498 |
| BW | Botswana | 104 | 9227 |
| PW | Palau | 107 | 471 |
| LB | Lebanon | 108 | 56 |
| GN | Guinea | 109 | 16453 |
| SL | Sierra Leone | 109 | 4587 |
| CV | Cabo Verde | 110 | 3625 |
| UZ | Uzbekistan | 111 | 2835 |
| PG | Papua New Guinea | 113 | 405 |
| ST | Sao Tome and Principe | 116 | 3658 |
| KH | Cambodia | 117 | 8301 |
| KM | Comoros | 117 | 15155 |
| SC | Seychelles | 118 | 3623 |
| CG | Congo (Republic) | 124 | 11918 |
| UG | Uganda | 126 | 7166 |
| SN | Senegal | 132 | 9556 |
| BF | Burkina Faso | 142 | 28929 |
| BS | Bahamas | 150 | 6922 |
| BB | Barbados | 150 | 23361 |
| GD | Grenada | 150 | 13755 |
| HT | Haiti | 150 | 9518 |
| KN | Saint Kitts and Nevis | 150 | 25176 |
| LC | Saint Lucia | 150 | 5189 |
| DM | Dominica | 156 | 4690 |
| BA | Bosnia and Herzegovina | 157 | 9637 |
| VC | Saint Vincent and the Grenadines | 157 | 1262 |
| GE | Georgia | 158 | 4075 |
| MU | Mauritius | 158 | 5451 |
| YE | Yemen | 158 | 3357 |
| LR | Liberia | 160 | 7848 |
| DJ | Djibouti | 165 | 3205 |
| KI | Kiribati | 165 | 3118 |
| MZ | Mozambique | 165 | 7309 |
| TG | Togo | 170 | 10915 |
| CD | DR Congo | 172 | 8860 |
| BH | Bahrain | 173 | 6755 |
| CM | Cameroon | 188 | 3280 |
| BT | Bhutan | 197 | 17392 |
| GY | Guyana | 200 | 2029 |
| HN | Honduras | 200 | 8266 |
| GW | Guinea-Bissau | 202 | 2196 |
| ML | Mali | 205 | 29924 |
| VE | Venezuela | 205 | 6392 |
| SY | Syria | 215 | 7194 |
| SB | Solomon Islands | 224 | 6049 |
| MG | Madagascar | 225 | 13117 |
| TL | Timor-Leste | 226 | 19779 |
| AE | United Arab Emirates | 237 | 12566 |
| BN | Brunei | 238 | 21383 |
| SV | El Salvador | 245 | 12937 |

Large legal systems that are still shallow (<1,000 laws): CN 295, MX 317, NG 362, KE 261, EG 407, TH 283 (78 articles), MA 482, SA 623, VN 700, ZA 822, IN 849, TR 917, PK 958, DZ 100, IQ 76.

Local corpora under `$IPFS_DATASETS_LEGAL_CORPORA_ROOT/<cc>/instruments` materially ahead of the Hub (candidate unpublished increments): CM local 363 vs Hub 188, DZ local 328 vs Hub 100, IQ local 225 vs Hub 76, MZ local 232 vs Hub 165, SN local 201 vs Hub 132, SV local 306 vs Hub 245, UG local 240 vs Hub 126. Local counts include raw instruments below the 80-char packaging floor, so they overstate publishable rows.

### (c) Non-country datasets

| Kind | Slug | Laws | Articles | Note |
|---|---|---:|---:|---|
| non_UN_state | kosovo | 90 | 1780 | Kosovo (not UN member) |
| non_UN_state | taiwan | 14966 | 307040 | Taiwan / ROC (not a UN member/observer) |
| subnational_municipal | andorra_municipal | 37430 | 6938 | parent=andorra |
| subnational_municipal | austria_municipal | 17432 | 66939 | parent=austria |
| subnational_municipal | brazil_municipal | 37797 | 242690 | parent=brazil |
| subnational_municipal | czech_municipal | 5066 | 31074 | parent=czech |
| subnational_municipal | estonia_municipal | 939 | 2279 | parent=estonia |
| subnational_municipal | ethiopia_municipal | 35 | 1034 | parent=ethiopia |
| subnational_municipal | jordan_municipal | 62 | 1205 | parent=jordan |
| subnational_municipal | kenya_municipal | 938 | 7968 | parent=kenya |
| subnational_municipal | korea_municipal | 42562 | 615385 | parent=korea |
| subnational_municipal | latvia_municipal | 7414 | 159630 | parent=latvia |
| subnational_municipal | malta_municipal | 332 | 1377 | parent=malta |
| subnational_municipal | mauritius_municipal | 67 | 1245 | parent=mauritius |
| subnational_municipal | mozambique_municipal | 10 | 479 | parent=mozambique |
| subnational_municipal | namibia_municipal | 3 | 68 | parent=namibia |
| subnational_municipal | netherlands_municipal | 87410 | 1238662 | parent=netherlands |
| subnational_municipal | palestine_municipal | 63 | 1116 | parent=palestine |
| subnational_municipal | peru_municipal | 4718 | 12029 | parent=peru |
| subnational_municipal | portugal_municipal | 0 | 0 | parent=portugal |
| subnational_municipal | saudi_arabia_municipal | 192 | 277 | parent=saudi_arabia |
| subnational_municipal | slovenia_municipal | 89859 | 874898 | parent=slovenia |
| subnational_municipal | south_africa_municipal | 175 | 4493 | parent=south_africa |
| subnational_municipal | tanzania_municipal | 403 | 5743 | parent=tanzania |
| subnational_municipal | tunisia_municipal | 4734 | 15690 | parent=tunisia |
| subnational_municipal | uganda_municipal | 15 | 365 | parent=uganda |
| subnational_municipal | zimbabwe_municipal | 11 | 122 | parent=zimbabwe |
| supranational | eu | 54102 | 143188 | European Union (EUR-Lex) |
| territory | anguilla | 617 | 29904 | UK overseas territory |
| territory | aruba | 175 | 1419 | Kingdom of Netherlands constituent |
| territory | bermuda | 1783 | 28040 | UK overseas territory |
| territory | british_virgin_islands | 175 | 9495 | UK overseas territory |
| territory | cayman | 175 | 20203 | UK overseas territory |
| territory | cookislands | 1036 | 14855 | Cook Islands (free association; non-UN) |
| territory | curacao | 175 | 5776 | Kingdom of Netherlands constituent |
| territory | hongkong | 1678 | 86041 | Hong Kong SAR |
| territory | montserrat | 1464 | 30234 | UK overseas territory |
| territory | niue | 99 | 2261 | Niue (free association; non-UN) |
| territory | puerto_rico | 175 | 3677 | US territory (arguably covered by USA skip) |
| territory | sint_maarten | 175 | 9073 | Kingdom of Netherlands constituent |
| territory | turks_caicos | 178 | 19088 | UK overseas territory |

Also inside country datasets: DE includes Landesrecht (DE-<Land>), ES includes autonomic law, CH includes cantonal law, GB has base+delta shards. Other datasets by the same author (not ipfs_*_laws): `legal_scrapers`, `american_municipal_law`, `ipfs_uk_local_acts`, `common_crawl_{pointers_by_collection,meta_indexes,municipal_index,state_index,federal_index}`, `Caselaw_Access_Project_JSON`, `211-info`, `211-ai-artifacts`, `ipfs_embeddings_test`.

### (d) Duplicate datasets for one country (consolidate)

- DO: endomorphosis/ipfs_dominicanrepublic_laws, endomorphosis/ipfs_dominican_republic_laws
- SV: endomorphosis/ipfs_elsalvador_laws, endomorphosis/ipfs_el_salvador_laws
- KP: endomorphosis/ipfs_northkorea_laws, endomorphosis/ipfs_north_korea_laws
- PG: endomorphosis/ipfs_papuanewguinea_laws, endomorphosis/ipfs_papua_new_guinea_laws
- SM: endomorphosis/ipfs_sanmarino_laws, endomorphosis/ipfs_san_marino_laws
- TT: endomorphosis/ipfs_trinidad_laws, endomorphosis/ipfs_trinidad_and_tobago_laws

The underscore-named variants are earlier or partial snapshots (several with 0 articles). `country_laws_ir/coverage.py` (`ALIAS_TO_CANONICAL`) treats the no-underscore slug as canonical.

## 2. Normalization status

### Raw layer (`endomorphosis/ipfs_*_laws`: `data/laws*.parquet` + `data/articles*.parquet`)

- Laws: **13 distinct column sets** over 240 datasets (one, portugal_municipal, has no laws parquet). **217 datasets share the canonical 19 columns**: `id, title, text, source_url, source_type, jurisdiction, country, language, eli, date, date_issued, retrieved_at, license, law_status, identifier, official_identifier, article_count, json_path, metadata_json`.
- The variants are municipal datasets that append columns (`municipality_id, municipality_name, wikidata_qid|municipality_qid` plus per-country extras such as `gn_number, gazette_number, gazette_date, commencement_date, text_backend, source_terms_note, national_law_id, act_type`): 22 datasets with 22-38 columns.
- Articles: **11 column sets**. 211 datasets have the canonical 9: `law_id, id, title, text, source_url, document_number, article_number, record_type, metadata_json`. 7 datasets have no articles parquet: eritrea, northkorea, trinidad_and_tobago, san_marino, north_korea, el_salvador, portugal_municipal.
- Dtype drift: `article_count` int32 x172 / int64 x67 / null x1; `eli` null-typed in 49 dataset(s) and `date` null-typed in 23; text columns string x183 vs large_string x56. About 23 datasets use sharded files (`laws-00001.parquet`...), a few add `data/manifest.json`, `PACK_META.json`, `manifests/`.
- The raw schema is declared in code only: `world_package.py` (`LAW_COLS`, `ART_COLS`) and `country_laws_ir/schema.py` (required: laws id/title/text; articles id/law_id/title/text; fails closed on null ids). No standalone schema doc or JSON-schema exists in `$IPFS_DATASETS_LEGAL_COLLECTORS_ROOT` or `$IPFS_DATASETS_PY_snip` (the snip dir only holds CC loader files and PDF tools).

### Normalized layer (exists)

- **country-laws-ir-graphrag/v1 (country_laws_ir v0.5.0)**, code in github.com/endomorphosis/ipfs_datasets_py : ipfs_datasets_py/processors/legal_scrapers/country_laws_ir/{schema,normalize,structure,package,upload,coverage,catalog}.py; CLI scripts in country_laws_ir_scripts/.
- Published as justicedao/ipfs_<slug>_laws_ir on Hub (217 datasets; code snapshot embedded in each repo under country_laws_ir/ + skill/query-country-laws-hf); 2 extra legacy 'ipfs_malta_laws-ir'/'ipfs_argentina_laws-ir'. All 217 country-level source datasets have an IR repo; 23 of the 25 `*_municipal` source datasets have none. `catalog.py` additionally marks belgium, portugal, lithuania, ghana as non-indexable (incomplete/thin).
- Normalized corpus parquet (`data/corpus/part-*.parquet`, <=4096 rows per file) has 47 columns: `record_type, source_dataset, source_revision, source_id, instrument_id, instrument_title, law_id, law_cid, article_number, article_title, title, body, body_sha256, jurisdiction, language, source_url, snapshot_date, coverage, license, collector, schema_version, entry_identity_schema_version, eli, identifier, official_identifier, source_type, country, law_status, parent_law_id, article_id, reconstructed_from_articles, hierarchy_kind, hierarchy_path, title_number, chapter_number, part_number, section_number, subsections, official_citation, bluebook_citation, cite_key, citation_status, pinpoint, entry_cid, title_length, body_length, document_length, document_index, corpus_index`. Retrieval unit is article/section with law-level fallback; entry and law ids are content CIDs (CIDv1 raw sha2-256 base32 over canonical JSON). BM25, graph and vector shards sit under `data/` (bm25, graph, vectors).
- Normalizer logic: `normalize.py` (HTML strip, article-vs-law unit choice, hierarchy detection), `structure.py` (title/chapter/part/section splitter), `profiles.py` (per-language heading lexicons; none for ar/zh/ja/ko, which are not force-split), `reconstruct.py`, `citations.py`, `package.py`, `upload.py` (writes only to `justicedao/*`), `coverage.py` (gap kinds missing/unpublished/stale/incomplete/stub_vectors).

### Are scrapers and normalizers published on the Hub?

- **Scrapers: yes, partially.** `endomorphosis/legal_scrapers` (dataset, 142 files) carries 84 per-country `collect_XX.py` plus common.py, archive_fallbacks.py, probe_cdx.py, world_lib.py, world_package.py, world_gap.json, world_scrape_status.md. Codes: AE, AL, AM, AR, AT, AU, BA, BD, BE, BG, BH, BO, BY, CA, CL, CN, CO, CR, CY, CZ, DK, DZ, EC, EE, EG, ET, FI, GE, GH, GR, HK, HR, HU, ID, IE, IS, IT, JM, JO, JP, KE, KZ, LK, LT, LU, LV, MA, MD, ME, MK, MN, MT, MY, NG, NO, NP, NZ, OM, PA, PE, PH, PK, PL, PT, PY, QA, RO, RS, RW, SE, SG, SI, SK, SN, TH, TN, TW, TZ, UA, UG, UY, UZ, VN, XK.
- Each country dataset also has its own `scrapers/` dir: 231/240 datasets, 1869 files total.
- Local collectors not yet in the aggregate Hub `legal_scrapers` repo (28): AF, AO, AZ, BN, BW, CM, CU, DO, FJ, GT, HN, IQ, IR, KH, LA, LB, MG, MW, MZ, NA, NI, PG, SS, SV, TT, VE, ZM, ZW. They exist in each dataset's own `scrapers/` dir.
- 83 covered countries have no dedicated `collect_XX.py` on the Hub, locally, or in GitHub `national_collectors/`. These are mostly small African/Caribbean/Pacific sets built by generic official-site crawl + CDX harvesters (e.g. `ingest_thin_cc_live.py`), plus DE/FR/GB/ES built by bulk collectors (`collect_gii/legi/legislation_gov_uk/boe`): AD, AG, BB, BF, BI, BJ, BR, BS, BT, BZ, CD, CF, CG, CH, CI, CV, DE, DJ, DM, ER, ES, FM, FR, GA, GB, GD, GM, GN, GQ, GW, GY, HT, IL, IN, KG, KI, KM, KN, KP, KR, KW, LC, LI, LR, LS, LY, MC, MH, ML, MR, MU, MV, MX, NE, NL, NR, PS, PW, RU, SA, SB, SC, SD, SL, SM, SO, SR, ST, SY, SZ, TD, TG, TJ, TL, TM, TO, TR, TV, VC, VU, WS, YE, ZA.
- **Normalizers: not in `endomorphosis/legal_scrapers`.** They live in GitHub `ipfs_datasets_py` (`country_laws_ir`) and as a code snapshot inside each `justicedao/ipfs_<slug>_laws_ir` repo. `world_package.py` is a raw packager (instruments JSON -> laws/articles parquet + README + MANIFEST), not a normalizer.
- No `endomorphosis/ipfs_*_scrapers` dataset exists.

## 3. ipfs_datasets_py `web_archiving` capabilities relevant to CC CDXJ / ranged WARC

Repo cloned blobless + sparse into `$IPFS_DATASETS_LEGAL_WORKSPACE/tmp/ipfs_datasets_py` (36 MB; a plain `git clone --depth 1` timed out). Two import paths exist: `ipfs_datasets_py/web_archiving/` (thin shim) and `ipfs_datasets_py/processors/web_archiving/` (implementation).

- `processors/web_archiving/common_crawl_integration.py`: `CommonCrawlSearchEngine` (modes local / remote-MCP / cli; `search_domain(domain, max_matches, collection)`, `fetch_warc_record(warc_filename, offset, length)`, **`fetch_warc_record_ranges_sliced(warc_filename, ranges)`** = coalesced bounded range reads then exact member split, `list_collections`, `get_collection_info`) and `create_search_engine()`; also HF meta-index/pointer lookups (`_search_domain_hf`).
- `processors/web_archiving/unified_web_scraper.py`: `UnifiedWebScraper` with `_scrape_common_crawl`, `_search_common_crawl_records(_bounded)`, range-slice fetch, and a fallback chain (Wayback, Archive.is, direct).
- `processors/web_archiving/unified_api.py`: `UnifiedWebArchivingAPI`, `UnifiedAPIConfig`; contracts `UnifiedSearchRequest/FetchRequest/Response`; orchestration `SearchPlanner`, `SearchExecutor`, `CircuitBreakerRegistry`, `RetryPolicy`, `execute_with_retry`, `ProviderScorer`.
- `processors/web_archiving/web_archive.py` (`WebArchive`): `create_warc`, `extract_text_from_warc`, `extract_metadata_from_warc`, `extract_links_from_warc`, `index_warc`, **`extract_dataset_from_cdxj`**. MCP wrappers in `mcp_server/tools/web_archive_tools/`: `search_common_crawl`, `get_common_crawl_content`, `list_common_crawl_indexes`, `search_common_crawl_advanced`, `fetch_warc_record_advanced`, `create_warc`, `index_warc`, `extract_dataset_from_cdxj`, `extract_*_from_warc`.
- `wayback_machine_engine.py`: `search_wayback_machine`, `get_wayback_content`, `fetch_wayback_cdx_rows`; also `ipwb_engine.py`, `archive_is_engine.py`, `cloudflare_browser_rendering_engine.py`, `web_text_extractor.py`, `agentic_scrape_optimizer.py` (`LegalStructuredFields`).
- `processors/legal_scrapers/common_crawl_index_loader.py`: `CommonCrawlIndexLoader` (`load_federal_index`, `load_state_index`, `load_municipal_index`, `load_pointers_index`, `load_meta_indexes`, `materialize_index_locally`, `query_state_index`, `query_municipal_index`, DuckDB sidecars). Hub indexes `endomorphosis/common_crawl_{federal,state,municipal}_index`, `common_crawl_pointers_by_collection`, `common_crawl_meta_indexes` exist, but they cover US federal/state/municipal. No world/national-gazette CC pointer index exists on the Hub.
- `processors/legal_scrapers/common_crawl_scraper.py`: `CommonCrawlLegalScraper` (`scrape_url`, `_fetch_common_crawl` with offset+range, fallback chain Brave -> Wayback -> unified -> direct).
- `processors/legal_scrapers/state_scrapers/state_warc_batch_downloader.py`: pattern for pointer parquet -> `_group_by_warc` -> `_coalesce_ranges` -> `_download_ranges_for_warc` -> `_split_records_to_html` (ranged WARC downloader; adaptable to country domains).
- `processors/legal_scrapers/international/` (`catalog.py`, `harvest.py`, `adapters.py`, `api.py`, `data/snapshot_catalog.json` with 205 entries incl. ISO `country_code`, `data/collector_inventory.json`) and `national_collectors/` (collectors for 109 country codes plus `archive_fallbacks.py`, `probe_cdx.py`).
- Local equivalents in `$IPFS_DATASETS_LEGAL_COLLECTORS_ROOT`: `archive_fallbacks.py` (`cc_indexes`, `search_common_crawl` via the index.commoncrawl.org HTTP API, `fetch_common_crawl_warc` = Range GET on data.commoncrawl.org, Wayback CDX), `ingest_{ao,gh,ir}_cc_warc.py`, `ingest_thin_cc_live.py`, `run_cc_probe_r4.py`. Its docstring says the S3 `cluster.idx` + CDXJ harvest is preferred over the HTTP index (often 0 hits or stalls).
- **Gap vs the goal:** the package's CC path is domain/URL-query oriented (DuckDB master index or HF pointer parquet). A direct S3 `cluster.idx` -> CDXJ shard range -> WARC range harvester keyed by official gazette domains is not packaged as one reusable function; `harvest_thin_s3_cc` is referenced only in comments and was not found in the tree. Building it (small per-country domain list + pointer parquet) is the main infrastructure task.

## 4. Remaining-work split (teammate packs BO AZ AL AO DO ET IR MW ZM LA LK TN RS and IT RO SI BG CY should not be reassigned; some still appear in tier lists because they are stubs on the Hub today)

- `Africa` thin/stub (40): SZ(56), SD(56), LY(69), CI(71), SO(77), BI(79), SS(80), GA(81), GQ(86), LS(90), CF(93), GM(94), TD(99), DZ(100), GH(101), TZ(101), ER(102), BJ(102), NE(102), BW(104), GN(109), SL(109), CV(110), ST(116), KM(117), SC(118), CG(124), UG(126), SN(132), BF(142), MU(158), LR(160), DJ(165), MZ(165), TG(170), CD(172), CM(188), GW(202), ML(205), MG(225)
- `MiddleEast_Asia_Pacific` thin/stub (20): AF(62), IQ(76), KP(84), VU(89), KW(93), PW(107), LB(108), UZ(111), PG(113), KH(117), GE(158), YE(158), KI(165), BH(173), BT(197), SY(215), SB(224), TL(226), AE(237), BN(238)
- `Americas_Europe` thin/stub (15): SR(94), BY(98), BS(150), BB(150), GD(150), HT(150), KN(150), LC(150), DM(156), BA(157), VC(157), GY(200), HN(200), VE(205), SV(245)

Recommended workstreams:

1. **WS-1 Normalization + publication infra** (no scraping): cast raw laws/articles to one pinned Arrow schema (int64 `article_count`, string types, municipal extras into `metadata_json`), consolidate the 6 duplicate repos, run `country_laws_ir` normalize over all country sets and decide on the 23 municipal sets, write a `NORMALIZED_SCHEMA.md`/JSON schema, and refresh `endomorphosis/legal_scrapers` with the 28 missing collectors plus the normalizer package and `world_package.py` (the upload needs user approval).
2. **WS-2 Africa deepening via CC S3 CDXJ + ranged WARC** (40 stub/thin countries): first build the shared `cc_s3_harvest` helper (cluster.idx -> CDXJ range -> WARC range, wrapping `CommonCrawlSearchEngine.fetch_warc_record_ranges_sliced`), then run per-country official-domain lists (`*.gov.xx` gazettes, parliament, AG).
3. **WS-3 Middle East / Asia / Pacific + big-system long tail**: AF IQ KP KW LB SY YE BH AE BT BN KH PG PW KI SB VU TL UZ GE, then depth for CN, IN, PK, VN, TH, TR, SA, NG, ID, MX; includes article-structure repair for KW/KP/ER/TH/EG and non-Latin heading profiles (ar, fa, zh, km, ko) in `profiles.py`.
4. **WS-4 Americas/Caribbean/Europe stubs + residual gaps**: SR BY BS BB GD HT KN LC DM VC GY HN VE SV BA; the one true missing state VA (Holy See); non-UN and territory sets (XK, TW, HK, CK, NU + the territories) depth checks; and publish-ready local increments (CM DZ IQ MZ SN SV UG are ahead of the Hub). Keep US/IS skipped.

## 5. Method / caveats

- Counts are row counts from parquet footers of `data/laws*.parquet` / `data/articles*.parquet` (summed over shards); where a README differs, the footer count is used.
- Country mapping is an explicit slug table in `$IPFS_DATASETS_LEGAL_WORKSPACE/tmp/audit/build_audit.py`; 0 unmapped. `fsm`=FM, `car`=CF, `drc`=CD, `congobrazzaville`=CG, `korea`=KR, `uae`=AE, `uk`=GB.
- Thin/stub flags measure dataset size, not true completeness; no external per-country ground truth was used. The 108 READMEs that say 'incomplete' are an independent signal.
- The box has no HF token file at `$HOME/.cache/huggingface/token`, so everything here used anonymous public reads. `pip install pycountry` into the venv failed (broken pip internals), so the ISO list is inline.
- Hub state is moving (teammates are uploading). Re-run `$IPFS_DATASETS_LEGAL_WORKSPACE/tmp/audit/{hub,footers,build_audit,final,report}.py` to refresh (about 3 minutes).
