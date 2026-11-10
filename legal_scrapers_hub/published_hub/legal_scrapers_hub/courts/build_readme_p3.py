import pyarrow.parquet as pq, json, collections, shutil, os, glob
D='/workspace/courts/hf_stage/dataset'; C='/workspace/courts'
cnt=json.load(open(f'{D}/PUBLISH_COUNTS.json'))
# per-source licences
lic=collections.defaultdict(collections.Counter); jur={}
for f in sorted(glob.glob(f'{D}/data/*/*/*.parquet')):
    for r in pq.read_table(f,columns=['source_name','licence','jurisdiction_raw','phase']).to_pylist():
        lic[(r['source_name'],r['jurisdiction_raw'])][r['licence']]+=1
rows=[]
for (s,j),c in sorted(lic.items(),key=lambda x:(str(x[0][1]),str(x[0][0]))):
    for l,n in c.items(): rows.append(f"| {s} | {j} | {n} | {l.replace('|','¦')} |")
cfg=[]
for p in ['phase1','phase2','phase3']:
    for t in ['court','rule','form','judge']:
        cfg.append(f"- config_name: {p}_{t}\n  data_files:\n  - split: train\n    path: data/{p}/{t}/part-0000.parquet")
for t in ['court','rule','form','judge']:
    cfg.append(f"- config_name: {t}\n  data_files:\n  - split: train\n    path: data/*/{t}/part-0000.parquet")
cfg.append("- config_name: default\n  data_files:\n  - split: train\n    path: data/*/court/part-0000.parquet")
tab="\n".join(f"| {k.split('/')[0]} | {k.split('/')[1]} | {v['in']} | {v['out']} |" for k,v in cnt['rows'].items())
rem="\n".join(f"| {r['phase']} | {r['type']} | {r['source_name']} | {r['matched']} | {r['rows']} |" for r in cnt['removed'])
tot=sum(v['out'] for v in cnt['rows'].values())
readme=f"""---
pretty_name: IPFS Court Data (world-courts-raw/v1)
license: other
license_name: per-source-see-card
language:
- en
- multilingual
size_categories:
- 10K<n<100K
task_categories:
- text-retrieval
tags:
- legal
- courts
- courthouses
- judges
- court-forms
- court-rules
- index-entries
- world-laws
- parquet
configs:
{chr(10).join(cfg)}
---

# IPFS Court Data — Courts & Courthouses (phases 1-3), `world-courts-raw/v1`

Part of the Endomorphosis *world-laws* project. Normalized, link-level metadata about courts, judges (official rosters / FJC in phases 1-2, best-effort court-page extraction in phase 3), court forms and court rules, gathered 2026-10-26 and 2026-10-27 from official public sources (live fetch, Wayback replays and Common Crawl). {tot:,} rows in total across four record types and three phases.

> **IMPORTANT CAVEAT — rules and forms are INDEX ENTRIES ONLY.** `rule` and `form` rows hold a title plus a link (`rule_url` / `file_url`) and where it was found. They do **not** contain the text of the rule or the form, and are not a substitute for the official documents. Court rows are names/addresses/contacts as published; judge rows contain only what is on official rosters (name, title, court, commission dates for FJC) in phases 1 and 2; phase 3 judge rows are best-effort extractions from court web pages, see the phase 3 section).

## Layout
`data/<phase>/<type>/part-0000.parquet` (zstd), types: `court`, `rule`, `form`, `judge`. Configs: one per type and phase (`phase1_court`, ..., `phase3_judge`), one per type across all three phases (`court`, `rule`, `form`, `judge`). Columns differ per type, so load each type separately. Full column definitions: [`SCHEMA_COURTS.md`](SCHEMA_COURTS.md). The pinned schema aligns with `world-laws-municipal/v1` (`country_iso`, `jurisdiction_level`, `admin_level`, `admin1`, `municipality`, `municipality_code`); municipality fields are null in these phases (phase 3 uses `US-XX` / `AU-XXX` / `CA-XX` ISO 3166-2 codes for `admin1`, and national rows have null `admin1`). Every row has `id`, `source_url`, `fetch_mode` (live/wayback/commoncrawl/derived), `retrieval_date`, `licence`, and `metadata_json` carrying all other source fields.

`id` is unique per row. The same link is often discovered on many pages, so `entity_key` identifies the content: dedupe on it for unique items (e.g. phase 1 rules: 2,327 distinct entities in 4,759 rows).

## Row counts (in = normalized, out = published)
| phase | type | normalized rows | published rows |
|---|---|---|---|
{tab}

## Exclusions
Records sourced from CanLII, AustLII, Cornell LII or eCourts bulk data were excluded (matching `source_url` / `found_on` host and `source_name`). Zero CanLII, AustLII or Cornell LII rows were present in any phase. Removed rows are all eCourts hosts (links found on Indian High Court sites, phase 1 only). Phase 3 removed 0 rows. Phase 3 matching used host labels (`canlii.*`, `austlii.*`, `law.cornell.edu`, `lii.*`, `ecourts*.`) because the bare substring used for phases 1 and 2 falsely flagged 11 unrelated rows (`washoecourts.com`, `darkecourts.com`, `statecourts` hosts), which were kept. Some phase 3 rows link to Wisconsin's own `wicourts.gov/ecourts/...` pages, and some URL paths contain the substring (e.g. `tc_aboutthecourts.php`); those are state court sites, not India's eCourts, and are kept.

| phase | type | source | matched | rows removed |
|---|---|---|---|---|
{rem}

## Wayback-only sources: Florida and South Carolina (robots.txt Disallow)
All 16 phase-2 `US-Florida` rows (10 forms, 5 rules, 1 court) were obtained only from web.archive.org `id_` replays (`fetch_mode=wayback`). `www.flcourts.gov/robots.txt` (checked 2026-10-26) disallows all paths (`Disallow: /`) for `User-agent: *` and allows only named bots, including ia_archiver. No live fetch of flcourts.gov was made. Future Florida work must stay Wayback-only. This note is repeated in each Florida row's `licence` and `metadata_json.robots_note`.

**Phase 3 additions.** Phase 3 adds 35 more `US-Florida` rows (13 courts, 3 rules, 19 forms) and 49 `US-South Carolina` rows (4 courts, 35 rules, 10 forms). `www.sccourts.org/robots.txt` also says `Disallow: /` for `User-agent: *` (with a very long crawl-delay), and `flcourts.gov` is unchanged. All 84 rows came from web.archive.org `id_` replays (`fetch_mode=wayback`); no live fetch of either site was made, and future work on both must stay Wayback-only. **Every one of these 84 rows is marked** with `metadata_json.wayback_only = true` and `metadata_json.robots_note`, and the note is appended to the row's `licence` column. (Phase 2 Florida rows carry the `robots_note` and licence suffix but not the `wayback_only` flag.)

## Phase 3 provenance and caveats
- **Source.** 69 sources (US state trial/county court sites, Canadian provinces, Australian states, NZ, UK, Ireland, Singapore and South Africa; 182 raw/dedup/clean manifest entries, regenerated 2026-10-27). Per source, the highest tier was used: `_clean` over `.dedup` over raw (`.dedup` = first-occurrence dedup; `_clean` = dedup plus judge cleanup of `title` / `full_name` / `raw_text`). The cleaned North Dakota, Singapore and South Africa files were produced by `tools/p3_post.py`, a re-implementation of the original cleaner. Scraper totals: 6,163 courts, 265 judges, 7,480 rules, 8,827 forms (22,735 rows). Jurisdictions: US, AU, CA, NZ, GB (UK), IE, SG, ZA. India district courts, Michigan and Oklahoma produced no data. Retrieval dates are 2026-10-26 and 2026-10-27.
- **UK courts are derived.** The 317 UK court rows have `fetch_mode = derived:phase1/UK_FaCT_locations.jsonl`: they were derived from the phase 1 UK court-finder (FaCT) data, so they overlap phase 1 UK `court` rows. Dedupe across phases on name and address if you need unique courts.
- **Best-effort judge extraction.** Judge rows from the North Dakota, Singapore and South Africa sources come from heuristic parsing of general web pages, not official rosters. They are marked `metadata_json.best_effort = true` with `best_effort_note`. In this dataset that is 3 rows (Singapore 1, South Africa 2; North Dakota's judge file has no rows left after cleaning) and they may be non-judges (news items, newsletters). All phase 3 judge rows (265 in total) are scraped from public court web pages, not from official rosters or FJC data, so check them against their `roster_url`.
- **Redactions.** Email addresses were replaced with `[email removed]` in all text columns (48 `address`, 46 `name`, 1 `file_url`, 1 `source_url` values; in 46 court rows the entire `name` was an email address) and servlet session-id URL parameters were removed from URLs (phase 1 and 2: 56 URLs; none were found in phase 3).
- **Duplicates.** Resumed runs and repeated navigation links produce many rows with the same `entity_key` (see `VALIDATION_phase3.json`); `id` stays unique.

## Licences and terms
Rows carry the licence of their source in the `licence` column (US federal: public domain, 17 USC 105; UK: OGL v3; otherwise "see TERMS.md" expanded with the source's terms row, generally government publication, link-level metadata only; India GODL/NDSAP; EU Decision 2011/833/EU etc. — see appendix). Site terms of the originating sites continue to apply; this dataset is provided as link-level metadata with attribution to the sources below. Please check the original source before reuse.

### Per-source licences (published rows)
| source | jurisdiction | rows | licence |
|---|---|---|---|
{chr(10).join(rows)}

## Local-only validation
Counts, null rates and duplicate analysis for the pre-exclusion data are in `VALIDATION_REPORT.md` and `VALIDATION_phase1.json` / `VALIDATION_phase2.json` / `VALIDATION_phase3.json` (pre-exclusion counts; subtract the eCourts rows listed above; the phase 3 file is already post-exclusion for `out_by_type` and lists `in_by_type` before exclusion).

## Appendix: TERMS.md (verbatim)
The appendix is the current `TERMS.md` as of the phase 3 publish (it includes the final phase 3 source statuses); the standalone `TERMS.md` file in this repo is the earlier phase 1/2 version, where phase 3 sources are still shown as pending.

"""+open(f'{C}/TERMS.md').read()
open(f'{D}/README.md','w').write(readme)
print(len(rows),'licence rows',tot)
