# State Admin WebArch Gap Audit

- Generated: `2026-03-07T10:38:29.927232+00:00`
- States audited: **14**
- Per-state workers: **8**
- Max seeds/state: **6**
- Max pages/state: **14**
- Max hops: **2**

## Summary

- States with substantive corpus signal: **4**
- States where probe found substantive pages: **5**
- States where probe found new substantive URLs outside corpus: **5**
- States blocked mainly by transport/access failures: **2**
- States fetchable but still non-substantive: **7**

## Per-State

| State | Corpus Rows | Corpus Substantive | Probe Success | Probe Substantive | New Substantive URLs | Gap Category |
|---|---:|---:|---:|---:|---:|---|
| AL | 6 | 0 | 1 | 0 | 0 | fetchable_but_non_substantive |
| AZ | 4 | 0 | 0 | 0 | 0 | blocked_or_transport_failures |
| GA | 9 | 3 | 12 | 0 | 0 | fetchable_but_non_substantive |
| IN | 1 | 1 | 9 | 0 | 0 | fetchable_but_non_substantive |
| MD | 1 | 0 | 6 | 0 | 0 | fetchable_but_non_substantive |
| MT | 1 | 0 | 9 | 2 | 2 | corpus_gap_probe_found_substantive |
| NH | 6 | 0 | 0 | 0 | 0 | blocked_or_transport_failures |
| NJ | 1 | 0 | 2 | 0 | 0 | fetchable_but_non_substantive |
| OK | 1 | 0 | 8 | 0 | 0 | fetchable_but_non_substantive |
| RI | 2 | 0 | 7 | 1 | 1 | corpus_gap_probe_found_substantive |
| SD | 2 | 0 | 4 | 1 | 1 | corpus_gap_probe_found_substantive |
| TX | 1 | 0 | 8 | 0 | 0 | fetchable_but_non_substantive |
| UT | 2 | 1 | 13 | 5 | 5 | has_substantive_signal |
| VT | 2 | 1 | 14 | 3 | 3 | has_substantive_signal |

## Priority Gaps

### AL

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.alabamaadministrativecode.state.al.us`, `https://www.sos.alabama.gov/alabama-administrative-code`, `https://legislature.al.gov/rules`, `https://legislature.al.gov/regulations`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

### AZ

- Gap category: `blocked_or_transport_failures`
- Seed URLs: `https://apps.azsos.gov/public_services/Title_00.htm`, `https://apps.azsos.gov/public_services`, `https://legislature.az.gov/rules`, `https://legislature.az.gov/regulations`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

### GA

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://rules.sos.ga.gov/gac`, `https://rules.sos.ga.gov`, `https://rules.sos.ga.gov/gac/90`, `https://dol.georgia.gov/individuals/job-search-assistance`

### IN

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://iar.iga.in.gov/code`, `https://iar.iga.in.gov/iac`, `https://iga.in.gov/legislative/laws/iac`, `https://www.in.gov/core/index.html`

### MD

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://mgaleg.maryland.gov/mgawebsite/Laws/Statutes`

### MT

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `https://rules.mt.gov`, `https://sosmt.gov/arm/register`, `https://sosmt.gov/arm/rulemaking-resources`, `https://leg.mt.gov`
- New substantive URLs: `https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74`, `https://rules.mt.gov/browse/collections/5e1173a6-33c7-4df8-b426-5e0077cfc430`

### NH

- Gap category: `blocked_or_transport_failures`
- Seed URLs: `https://gc.nh.gov/rules/state_agencies`, `https://gc.nh.gov/rules`, `https://www.gencourt.state.nh.us/rules/state_agencies`, `https://www.gencourt.state.nh.us/rules`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

### NJ

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.njleg.state.nj.us`

### OK

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.sos.ok.gov/rules/default.aspx`, `https://www.sos.ok.gov/rules`

### RI

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations`, `https://rules.sos.ri.gov`, `https://web.archive.org/web/20121004042026/http:/webserver.rilin.state.ri.us/Statutes/TITLE3/3-8/INDEX.HTM`, `https://web.archive.org/web/20121004042026/http:/webserver.rilin.state.ri.us/Statutes/TITLE4/4-13.1/INDEX.HTM`
- New substantive URLs: `https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations/building-and-fire-codes`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

### SD

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `https://rules.sd.gov`, `https://rules.sd.gov/default.aspx`, `https://sdlegislature.gov/Rules/Administrative`
- New substantive URLs: `https://sdlegislature.gov/Rules/Administrative`

### TX

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.sos.state.tx.us/tac/index.shtml`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=SEARCH_TAC`, `https://www.sos.state.tx.us/texreg/index.shtml`
