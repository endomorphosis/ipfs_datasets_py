---
pretty_name: JusticeDAO Legal Scrapers (research collectors)
license: agpl-3.0
language:
- en
tags:
- legal
- scrapers
- collectors
- official-sources
- research
- wayback
- common-crawl
task_categories:
- text-retrieval
---

# JusticeDAO Legal Scrapers

Research collectors that download **official** legislative sources only
(national gazettes and official open-data portals). Intended for building
reproducible legal-text corpora, not for production legal research products.

**Not legal advice.** The official gazette of each jurisdiction prevails.

## License

**AGPL-3.0** for the collector scripts in this repository.

## Contents

`scrapers/` includes country collectors, EU/EUR-Lex, shared helpers, and
archive-fallback utilities. Collectors target **official gazettes and official
open-data portals only**. Cyprus (`collect_cy.py`) uses the Government Printing
Office at mof.gov.cy/gpo; cylaw.org is unofficial and is **not** included.

### Shared helpers

- `collector.py`, `common.py`, `collect_remaining.py`
- `archive_fallbacks.py` — Wayback Machine and Common Crawl CDX lookups
- `probe_cdx.py` — CDX probe helper
- `collect_blocked_archives.py` — archive fallbacks for blocked official hosts
- `collect_pt_ro_lt_archives.py` — PT/RO/LT Wayback and Common Crawl fallbacks
- `collect_spa_playwright.py` — Playwright SPA rendering for JS-only official portals

### EU and large official corpora

- `collect_eurlex.py` (EU)
- `collect_gii.py` (DE, Gesetze im Internet)
- `collect_boe.py` (ES, Boletín Oficial del Estado)
- `collect_bwb.py` (NL, Basiswettenbestand)
- `collect_legi.py` (FR, Légifrance)
- `collect_fedlex.py` (CH, Fedlex)

### EU member-state collectors

- `collect_at.py` (Austria)
- `collect_be.py` (Belgium)
- `collect_bg.py` (Bulgaria)
- `collect_cy.py` (Cyprus — official GPO / mof.gov.cy only)
- `collect_cz.py` (Czechia)
- `collect_dk.py` (Denmark)
- `collect_ee.py` (Estonia)
- `collect_fi.py` (Finland)
- `collect_gr.py` (Greece)
- `collect_hr.py` (Croatia)
- `collect_hu.py` (Hungary)
- `collect_ie.py` (Ireland)
- `collect_it.py` (Italy)
- `collect_lt.py` (Lithuania)
- `collect_lu.py` (Luxembourg)
- `collect_lv.py` (Latvia)
- `collect_mt.py` (Malta)
- `collect_pl.py` (Poland)
- `collect_pt.py` (Portugal)
- `collect_ro.py` (Romania)
- `collect_se.py` (Sweden)
- `collect_si.py` (Slovenia)
- `collect_sk.py` (Slovakia)
- `collect_egov_laws.py` (Japan, e-Gov 法令検索)
- `collect_justice_laws.py` (Canada, Justice Laws XML)

### Mexico and China collectors

- `collect_leyes_biblio.py` (Mexico, Cámara de Diputados LeyesBiblio)
- `collect_npc_flk.py` (China, NPC 权威发布 / official HTML)
- `fill_cn.py` (China, second-pass PDF + Wayback fill)

### Archive fallbacks

When a live official host is blocked, incomplete, or JS-only, collectors may
use:

- **Wayback Machine** CDX/capture replay of the official URL
- **Common Crawl** CDX indexes of the official URL
- **Playwright** for official single-page applications that do not emit HTML
  without a browser

Fallbacks still retrieve official gazette or official-portal snapshots only.
They do not substitute unofficial aggregators (including cylaw.org).

### Additional official collectors

- `collect_lom_agc.py` (my)

### Additional official collectors

- `collect_peraturan.py` (id)

### Additional official collectors

- `collect_sso_agc.py` (sg)

## Disclaimer

These scripts are research tools. They do not produce official consolidations.
**Not legal advice.** The official gazette prevails.

### Other official national collectors

- `collect_indiacode.py` (India, India Code Central Acts)
- `collect_knesset_laws.py` (Israel, Knesset OData / Reshumot PDFs)
- `collect_boe_laws.py` (Saudi Arabia, BOE laws.boe.gov.sa — Wayback of official URLs)
- `collect_kuwaitalyawm.py` (Kuwait, الكويت اليوم category القوانين + e.gov.kw)
- `collect_egov_laws.py` (Japan, e-Gov 法令検索)
- `collect_justice_laws.py` (Canada)
- `collect_jp.py` / `collect_ca.py` aliases where present
- `collect_federal_register.py` (Australia, Federal Register of Legislation / FRL; Acts-first, CC BY 4.0)
- `collect_pco_legislation.py` (New Zealand, PCO / legislation.govt.nz public acts; Wayback of official URLs; no live WAF bypass)

## Refresh 2026-10-10: more collectors, shared helpers, normalizer, schema

- `scrapers/collect_{af,bn,bw,cm,cu,fj,gt,hn,iq,kh,lb,mg,mz,na,ni,pg,ss,sv,tt,ve,zw}.py` — collectors that previously only lived in each
  country dataset's own `scrapers/` directory (Afghanistan, Brunei, Botswana, Cameroon, Cuba, Fiji, Guatemala, Honduras, Iraq, Cambodia,
  Lebanon, Madagascar, Mozambique, Namibia, Nicaragua, Papua New Guinea, South Sudan, El Salvador, Trinidad and Tobago, Venezuela, Zimbabwe).
  AZ, AO, DO, IR, LA, MW, ZM follow once their packs are no longer being actively deepened.
- `scrapers/{common,world_lib,archive_fallbacks,pdf_extract_lib,world_package}.py` refreshed to the versions the collectors above import
  (`world_lib.fetch_official_prefer_pdf`, `pdf_extract_lib` were missing here).
- `normalizers/` — snapshot of the `country_laws_ir` normalizer (upstream `endomorphosis/ipfs_datasets_py`), CLI scripts, a shard-support patch,
  `pack_raw_for_ir.py` and `schema.py`. See `normalizers/NORMALIZER_VERSION.md`.
- `SCHEMA.md` — the pinned raw `ipfs_<slug>_laws` Arrow schema (string text columns, int64 `article_count`, municipal extras folded
  into `metadata_json`) and the normalized `justicedao/ipfs_<slug>_laws_ir` schema.
