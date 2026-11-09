# Lane pipelines (integrated 2026-11-08)

Reusable collectors, stagers, verifiers and schema code from the county, municipal, case-law,
courts, state-law, regulations/executive-order and US city-code lanes. National-law collectors
and shared helpers already live in `../../../national_collectors/` and
`../../hub_dataset_scripts/endomorphosis__legal_scrapers/`; those newer upstream copies were kept.

| Directory | Lane | Origin (lane workspace) |
|---|---|---|
| `counties/lanes/gb` | UK local-authority byelaws (UKLA) fetch, OCR, pack build | `legal-corpora/county/GB/scrapers` |
| `counties/lanes/ke` | Kenya county laws (incl. Samburu), alt fetch, OCR, staging, verify | `legal-corpora/county/KE/{scrapers,hub_head/scrapers}` |
| `counties/lanes/us` | US county codes: Wayback/CC gap fill, site crawl, OCR, shard build | `legal-corpora/county/US/scrapers` |
| `counties/lanes/us_city_codes` | US city-code candidate discovery (Wikidata) | `us_city_codes` |
| `municipal_lanes/za/{prov,mun}` | South Africa provincial gazettes and metro by-laws | `legal-corpora/municipal/za_build_state/hub/{prov,mun}/scrapers` |
| `municipal_lanes/na` | Namibia (Walvis Bay) municipal | `legal-corpora/municipal/na_build_state/hub/mun/scrapers` |
| `municipal_lanes/jo_ps` | Jordan + Palestine (MoLG) municipal | `legal-corpora/municipal/jo_build_state/hub/mun/scrapers` |
| `caselaw/pipeline` | Case-law raw schema (`caselaw-raw/v0`), court matcher, jobs (CJEU, NL, CH, BR, CourtListener non-CAP), migrations, fixture runner | `case_law/pipeline` |
| `courts/lanes` | Court directory phases 1-4, robots helper, EU courts schema, Kenya crawl | `courts`, `courts_europe`, `courts_asia_africa` |
| `states/lanes` | State-law source list generation and host checks | `state_laws` |
| `national/us/collect_eo_federal_register.py`, `collect_ecfr_appendices.py` | US executive orders (Federal Register API) and eCFR appendices | `regs_eo` |

## Paths

Hard-coded workspace paths were replaced with the repository's existing convention:

- `IPFS_DATASETS_LEGAL_CORPORA_ROOT` (default `~/.ipfs_datasets/legal_corpora`), formerly `<workspace>/legal-corpora`
- `WORLD_LAW_ROOT` (default `~/.ipfs_datasets/world_law`)
- `IPFS_DATASETS_LEGAL_WORKSPACE` (default `~/.ipfs_datasets/legal_workspace`): root for the other lanes
  (`case_law/`, `courts/`, `regs_eo/`, `state_laws/` ...). Set it to the old workspace root to reproduce the original layout exactly.
- `IPFS_DATASETS_PY` (optional): a checkout to put on `sys.path` before the installed package.

Helper modules (`polite`, `packlib`, `robots_guard`) are vendored next to the scripts that import them,
which follows the existing collector layout. Scripts keep their original robots.txt, disk and memory guards.

Not included: raw or staged data, logs, batch-specific patch/refill/verify scripts, `*.bak*`/`pre_*` copies,
versioned superseded runs, vendored third-party libraries, and fixtures derived from real records.
Datasets are published on Hugging Face, not here.

Tests: `tests/unit/legal_scrapers/test_lane_pipelines_portability.py`.

## Follow-up (2026-11-08 p1)

Additional reusable pieces landed after the initial lane commit:

- `caselaw/pipeline/docs/` — schema_caselaw_v0..v6 + doc_v6_head/tail; `gen_schema_doc.py` reads these first
- `municipal_lanes/gr/` — Diavgeia OCR fetch/ocr/row-build (helpers in `hub_integrated/legal_scrapers/municipal/`)
- `counties/lanes/us_city_codes/{collect,build,probe}.py` — open municipal-code collector (excludes `t.py`)
- `packaging/africa_me/` — Africa/MENA pack builder, gates, merge_b2, quality filters, domains
- `hub_dataset_scripts/endomorphosis__legal_scrapers/scrapers/world_package.py` — expanded META catalog + `MIN_PACKAGE_TEXT`
- `hub_dataset_scripts/endomorphosis__legal_scrapers/docs/` — curated operational READMEs / coverage status (not live NORMALIZER_STATUS)
