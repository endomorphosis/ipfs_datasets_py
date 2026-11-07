# STATUS — Asia/Pacific + Americas/Caribbean + Europe stubs + big systems (executor lane)

Updated: 2026-10-10 17:11 PT. Packages only; **no Hub upload** (Chief of Staff 34f8a6df owns uploads). Pack root: `~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/<cc>/{data/laws.parquet,data/articles.parquet,README.md,MANIFEST.md}`.
Work dir / scripts: `/workspace/asia_americas_europe/` (article_repair.py, repair_pack.py, pack_local.py, verify_packs.py, cc_country_harvest.py, va/).
Schema: raw 19-col laws / 9-col articles as published (Normalizer owns the Arrow schema; unchanged). Hub rows are carried verbatim in every pack (additive only; text/title byte-equal to the live Hub, verified by verify_packs.py).
CC helper `legal_scrapers/common_crawl_helper.py` (Africa&MENA bot) landed 15:17 PT and is used for VA and all harvests (ranged reads only).
Resource guard: MemAvailable >= 3.5 GiB, disk >= 20 GiB (helper enforces; at start 11.9 GiB / 29 GiB).

## 1. Article-structure repair (packs READY)
| CC | Hub laws/articles before | pack laws/articles | repaired laws | note |
|---|---|---|---|---|
| KW | 93 / 0 | 93 / 519 | 12 | Arabic PDF-extraction glyph forms NFKC/bidi/tatweel-cleaned for matching and in new article text; remaining 81 are forms/tables/statistical releases without enumerated articles |
| KP | 84 / 0 | 84 / 4026 | 83 | 제N조 and Article N splits |
| ER | 102 / 0 | 102 / 4070 | 90 | Art./Article/Section N splits |
| EG | 407 / 1458 | 407 / 1562 | 39 | only laws with 0 existing article rows touched; existing rows verbatim |
| TH | 283 / 78 | not packed | 0 | Thai PUA normalised; only 19/283 rows contain enumerated มาตรา/ข้อ lines and they already have article rows. Rest are Royal Gazette *pages* (หน้า N) = notices; not splittable. Needs new sources (Krisdika statutes), see big systems. |
Law `text`/`title` unchanged; `article_count` set to number of article rows.

## 2. All packs currently in ready_asia_americas_europe (additive over live Hub; Hub rows verbatim)
| CC | hub repo | hub laws→ | hub arts→ | pack laws | pack arts | new laws | new arts | path |
|---|---|---|---|---|---|---|---|---|
| BA | endomorphosis/ipfs_bosnia_laws | 157 | 9637 | 160 | 9642 | 3 | 5 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/ba |
| BB | endomorphosis/ipfs_barbados_laws | 150 | 23361 | 163 | 23601 | 13 | 240 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/bb |
| BS | endomorphosis/ipfs_bahamas_laws | 150 | 6922 | 301 | 8605 | 151 | 1683 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/bs |
| BT | endomorphosis/ipfs_bhutan_laws | 197 | 17392 | 198 | 17670 | 1 | 278 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/bt |
| BY | endomorphosis/ipfs_belarus_laws | 98 | 7335 | 125 | 9258 | 27 | 1923 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/by |
| CM | endomorphosis/ipfs_cameroon_laws | 188 | 3280 | 411 | 5086 | 223 | 1806 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/cm |
| CN | endomorphosis/ipfs_china_laws | 295 | 21454 | 315 | 22043 | 20 | 589 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/cn |
| DM | endomorphosis/ipfs_dominica_laws | 156 | 4690 | 190 | 5241 | 34 | 551 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/dm |
| DZ | endomorphosis/ipfs_algeria_laws | 100 | 492 | 296 | 13721 | 196 | 13229 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/dz |
| EG | endomorphosis/ipfs_egypt_laws | - | - | 407 | 1562 | - | - | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/eg |
| ER | endomorphosis/ipfs_eritrea_laws | - | - | 102 | 4070 | - | - | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/er |
| GD | endomorphosis/ipfs_grenada_laws | 150 | 13755 | 151 | 13831 | 1 | 76 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/gd |
| GY | endomorphosis/ipfs_guyana_laws | 200 | 2029 | 206 | 2126 | 6 | 97 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/gy |
| HN | endomorphosis/ipfs_honduras_laws | 200 | 8266 | 209 | 10550 | 9 | 2284 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/hn |
| HT | endomorphosis/ipfs_haiti_laws | 150 | 9518 | 151 | 9521 | 1 | 3 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/ht |
| ID | endomorphosis/ipfs_indonesia_laws | 1924 | 105645 | 2088 | 110938 | 164 | 5293 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/id |
| IN | endomorphosis/ipfs_india_laws | 849 | 35400 | 980 | 38340 | 131 | 2940 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/in |
| IQ | endomorphosis/ipfs_iraq_laws | 76 | 335 | 217 | 2653 | 141 | 2318 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/iq |
| KI | endomorphosis/ipfs_kiribati_laws | 165 | 3118 | 168 | 3240 | 3 | 122 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/ki |
| KP | endomorphosis/ipfs_northkorea_laws | - | - | 84 | 4026 | - | - | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/kp |
| KW | endomorphosis/ipfs_kuwait_laws | - | - | 93 | 519 | - | - | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/kw |
| LC | endomorphosis/ipfs_saint_lucia_laws | 150 | 5189 | 154 | 6187 | 4 | 998 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/lc |
| MX | endomorphosis/ipfs_mexico_laws | 317 | 44168 | 460 | 56654 | 143 | 12486 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/mx |
| MZ | endomorphosis/ipfs_mozambique_laws | 165 | 7309 | 229 | 8176 | 64 | 867 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/mz |
| NG | endomorphosis/ipfs_nigeria_laws | 362 | 11021 | 366 | 11058 | 4 | 37 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/ng |
| PK | endomorphosis/ipfs_pakistan_laws | 958 | 41876 | 966 | 41938 | 8 | 62 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/pk |
| SA | endomorphosis/ipfs_saudiarabia_laws | 623 | 10467 | 646 | 11126 | 23 | 659 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/sa |
| SB | endomorphosis/ipfs_solomonislands_laws | 224 | 6049 | 226 | 6391 | 2 | 342 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/sb |
| SN | endomorphosis/ipfs_senegal_laws | 132 | 9556 | 241 | 12269 | 109 | 2713 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/sn |
| SR | endomorphosis/ipfs_suriname_laws | 94 | 2164 | 99 | 2330 | 5 | 166 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/sr |
| SV | endomorphosis/ipfs_elsalvador_laws | 245 | 12937 | 306 | 13998 | 61 | 1061 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/sv |
| TL | endomorphosis/ipfs_timorleste_laws | 226 | 19779 | 287 | 20720 | 61 | 941 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/tl |
| TR | endomorphosis/ipfs_turkey_laws | 917 | 37879 | 927 | 37968 | 10 | 89 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/tr |
| UG | endomorphosis/ipfs_uganda_laws | 126 | 7166 | 127 | 7166 | 1 | 0 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/ug |
| UZ | endomorphosis/ipfs_uzbekistan_laws | 111 | 2835 | 335 | 7914 | 224 | 5079 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/uz |
| VA | - | - | - | 400 | 1222 | - | - | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/va |
| VC | endomorphosis/ipfs_saint_vincent_grenadines_laws | 157 | 1262 | 158 | 1262 | 1 | 0 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/vc |
| VN | endomorphosis/ipfs_vietnam_laws | 700 | 41042 | 771 | 42237 | 71 | 1195 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/vn |
| VU | endomorphosis/ipfs_vanuatu_laws | 89 | 1062 | 93 | 1107 | 4 | 45 | ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe/vu |

Integrity (verify2.py, run 17:0x PT; output `/workspace/asia_americas_europe/verify2.out`): for every pack with a local Hub snapshot, hub_missing=0 and hub_text_diff=0 (all Hub laws present and title/text byte-equal), orphan article rows=0, null id/title/text=0. `sum(article_count)==articles` for all except IQ, SN, VU (pre-existing Hub article_count values retained verbatim; not mine to change). Duplicate article ids exist in many *Hub-origin* article sets (pre-existing Hub issue, e.g. UG, GD, TL, MX); new article ids added by me are unique (asserted).

## 3. Not packed / no new material
TH (no new rows after gate; Hub text is Royal Gazette pages), AF, PW (no pointers/gated out), KN (0), PG (already in Hub), KH (all already in Hub). 
## 4. Blockers / notes
- PK: pakistancode.gov.pk / na.gov.pk / senate.gov.pk have 0 Common Crawl CDX pointers; only sindhlaws.gov.pk + molaw.gov.pk yielded (8 new laws).
- ID: peraturan.bpk.go.id has 0 pointers; peraturan.go.id + jdih.kemenkeu/esdm yielded +164.
- TR: mevzuat.gov.tr 0 pointers under either host; tbmm.gov.tr, kvkk.gov.tr, anayasa.gov.tr yielded +10 laws. Hub TR already has 917 laws / 37,879 articles. (Earlier "121 new laws, 0 articles" observation was pre-gate; those were constitutional-history commentary pages and were quarantined.)
- SA: laws.boe.gov.sa 0 pointers (uqn.gov.sa only).
- UZ: lex.uz acts are versioned (`?ONDATE=`), so some new rows are historical versions of the same act (distinct source_url); titles contain lex.uz header chrome. Added `N-modda` article splitting (5079 articles).
- VA: 400 instruments (Vatican City State laws incl. OCR of scanned PDFs + Canon Law 1983 CIC); OCR text may contain noise; OCR capped at 40 pages/document.
- BA/HN/etc: many CC candidates already in Hub (dedup by id/url).
- Box memory pressure from other agents (10 GB verify job) paused heavy steps; harvest/repack scripts now wait for MemAvailable>=3.5 GiB.
