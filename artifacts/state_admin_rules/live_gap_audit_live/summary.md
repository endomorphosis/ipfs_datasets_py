# State Admin WebArch Gap Audit

- Generated: `2026-03-08T08:11:48.472278+00:00`
- States audited: **12**
- Per-state workers: **8**
- Max seeds/state: **6**
- Max pages/state: **8**
- Max hops: **1**

## Summary

- States with substantive corpus signal: **4**
- States where probe found substantive pages: **4**
- States where probe found new substantive URLs outside corpus: **4**
- States where probe found only landing-page candidates: **4**
- States blocked mainly by transport/access failures: **1**
- States fetchable but still non-substantive: **4**

## Per-State

| State | Corpus Rows | Corpus Substantive | Probe Success | Probe Substantive | Probe Landing Candidates | New Substantive URLs | Gap Category |
|---|---:|---:|---:|---:|---:|---:|---|
| AL | 6 | 0 | 7 | 1 | 1 | 1 | corpus_gap_probe_found_substantive |
| AZ | 4 | 0 | 0 | 0 | 0 | 0 | blocked_or_transport_failures |
| GA | 9 | 2 | 8 | 0 | 0 | 0 | fetchable_but_non_substantive |
| IN | 1 | 1 | 8 | 0 | 0 | 0 | fetchable_but_non_substantive |
| MI | 2 | 0 | 8 | 0 | 2 | 0 | corpus_gap_with_landing_candidates |
| MT | 1 | 0 | 8 | 1 | 4 | 1 | corpus_gap_probe_found_substantive |
| NH | 6 | 0 | 2 | 0 | 2 | 0 | corpus_gap_with_landing_candidates |
| RI | 2 | 0 | 8 | 3 | 0 | 3 | corpus_gap_probe_found_substantive |
| SD | 2 | 0 | 4 | 0 | 1 | 0 | corpus_gap_with_landing_candidates |
| TX | 1 | 0 | 7 | 0 | 0 | 0 | fetchable_but_non_substantive |
| UT | 2 | 1 | 7 | 0 | 4 | 0 | fetchable_but_non_substantive |
| VT | 2 | 1 | 8 | 5 | 1 | 5 | has_substantive_signal |

## Priority Gaps

### AL

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `http://www.alabamaadministrativecode.state.al.us`, `https://www.alabamaadministrativecode.state.al.us`, `https://admincode.legislature.state.al.us`, `https://admincode.legislature.state.al.us/administrative-code`
- New substantive URLs: `https://admincode.legislature.state.al.us/administrative-code`
- Landing-page candidates: `https://admincode.legislature.state.al.us/search`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

### AZ

- Gap category: `blocked_or_transport_failures`
- Seed URLs: `https://apps.azsos.gov/public_services/Title_00.htm`, `https://apps.azsos.gov/public_services`, `https://legislature.az.gov/rules`, `https://legislature.az.gov/regulations`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

### GA

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://rules.sos.ga.gov/gac`, `https://rules.sos.ga.gov`, `https://rules.sos.ga.gov/gac/90`, `https://dol.georgia.gov/individuals/job-search-assistance`

### IN

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://iar.iga.in.gov/code`, `https://iar.iga.in.gov/code/2006`, `https://iar.iga.in.gov/sitemap.xml`, `https://iar.iga.in.gov/iac`

### MI

- Gap category: `corpus_gap_with_landing_candidates`
- Seed URLs: `http://www.legislature.mi.gov/Laws/ChapterIndex`, `https://www.legislature.mi.gov/Laws/ChapterIndex`, `https://www.legislature.mi.gov`, `https://www.legislature.mi.gov/rules`
- Landing-page candidates: `https://www.legislature.mi.gov/regulations`, `https://www.legislature.mi.gov/administrative-code`

### MT

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `https://rules.mt.gov`, `https://rules.mt.gov/browse/collections`, `https://rules.mt.gov/search`, `https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74`
- New substantive URLs: `https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/29483f1f-4f3a-43f5-9dc2-176385fba890`
- Landing-page candidates: `https://rules.mt.gov/browse/collections`, `https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74`, `https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/1f2ff5c5-b709-420b-bdd4-f6009ca7d33f`, `https://rules.mt.gov/browse/collections/5e1173a6-33c7-4df8-b426-5e0077cfc430`

### NH

- Gap category: `corpus_gap_with_landing_candidates`
- Seed URLs: `https://gc.nh.gov/rules/state_agencies`, `https://gc.nh.gov/rules`, `https://www.gencourt.state.nh.us/rules/state_agencies`, `https://www.gencourt.state.nh.us/rules`
- Landing-page candidates: `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules`, `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

### RI

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations`, `https://rules.sos.ri.gov`, `https://rules.sos.ri.gov/regulations/part/510-00-00-1`, `https://rules.sos.ri.gov/regulations/part/510-00-00-2`
- New substantive URLs: `https://rules.sos.ri.gov/regulations/part/510-00-00-1`, `https://rules.sos.ri.gov/regulations/part/510-00-00-2`, `https://rules.sos.ri.gov/regulations/part/510-00-00-3`

### SD

- Gap category: `corpus_gap_with_landing_candidates`
- Seed URLs: `https://rules.sd.gov`, `https://rules.sd.gov/default.aspx`, `https://sdlegislature.gov/Rules/Administrative`
- Landing-page candidates: `https://sdlegislature.gov/Rules/Administrative`

### TX

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.sos.state.tx.us/tac/index.shtml`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=SEARCH_TAC`, `https://www.sos.state.tx.us/texreg/index.shtml`

### UT

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://rules.utah.gov`, `https://adminrules.utah.gov`, `https://adminrules.utah.gov/public/home`, `https://adminrules.utah.gov/public/search`
- Landing-page candidates: `https://rules.utah.gov`, `https://rules.utah.gov/utah-administrative-code`, `https://rules.utah.gov/march-1-2026-issue-of-the-utah-state-bulletin-is-now-available`, `https://rules.utah.gov/february-15-2026-issue-of-the-utah-state-bulletin-is-now-available`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`
