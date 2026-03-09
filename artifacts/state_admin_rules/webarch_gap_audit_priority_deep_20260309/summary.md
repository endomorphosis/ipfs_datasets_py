# State Admin WebArch Gap Audit

- Generated: `2026-03-09T05:31:21.574538+00:00`
- States audited: **13**
- Per-state workers: **6**
- Max seeds/state: **6**
- Max pages/state: **14**
- Max hops: **2**

## Summary

- States with substantive corpus signal: **5**
- States where probe found substantive pages: **3**
- States where probe found new substantive URLs outside corpus: **3**
- States where probe found only landing-page candidates: **4**
- States blocked mainly by transport/access failures: **1**
- States fetchable but still non-substantive: **3**

## Per-State

| State | Corpus Rows | Corpus Substantive | Probe Success | Usable Success | Probe Substantive | Probe Landing Candidates | New Substantive URLs | Gap Category |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| AL | 6 | 0 | 6 | 6 | 0 | 0 | 0 | fetchable_but_non_substantive |
| AZ | 4 | 0 | 0 | 0 | 0 | 0 | 0 | blocked_or_transport_failures |
| GA | 9 | 2 | 14 | 14 | 1 | 7 | 1 | has_substantive_signal |
| IN | 1 | 1 | 10 | 10 | 0 | 0 | 0 | has_substantive_signal |
| MI | 2 | 0 | 14 | 14 | 0 | 1 | 0 | corpus_gap_with_landing_candidates |
| MS | 3 | 3 | 10 | 10 | 0 | 0 | 0 | has_substantive_signal |
| MT | 1 | 0 | 14 | 8 | 0 | 2 | 0 | corpus_gap_with_landing_candidates |
| NH | 6 | 0 | 14 | 14 | 3 | 3 | 3 | corpus_gap_probe_found_substantive |
| OH | 4 | 4 | 13 | 13 | 0 | 1 | 0 | has_substantive_signal |
| RI | 2 | 0 | 14 | 9 | 2 | 5 | 2 | corpus_gap_probe_found_substantive |
| SD | 2 | 0 | 13 | 13 | 0 | 0 | 0 | fetchable_but_non_substantive |
| TX | 1 | 0 | 14 | 12 | 0 | 0 | 0 | fetchable_but_non_substantive |
| UT | 2 | 1 | 11 | 11 | 0 | 1 | 0 | has_substantive_signal |

## Priority Gaps

### AL

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `http://www.alabamaadministrativecode.state.al.us`, `https://www.alabamaadministrativecode.state.al.us`, `https://admincode.legislature.state.al.us`, `https://admincode.legislature.state.al.us/administrative-code`

### AZ

- Gap category: `blocked_or_transport_failures`
- Seed URLs: `https://apps.azsos.gov/public_services/Title_00.htm`, `https://apps.azsos.gov/public_services`, `https://legislature.az.gov/rules`, `https://legislature.az.gov/regulations`
- Blocked examples: `beautifulsoup error: 403 Client Error: Forbidden for url: https://apps.azsos.gov/public_services/Title_00.htm; requests_`, `beautifulsoup error: 403 Client Error: Forbidden for url: https://apps.azsos.gov/public_services; requests_only error: 4`

### MI

- Gap category: `corpus_gap_with_landing_candidates`
- Seed URLs: `https://ars.apps.lara.state.mi.us`, `https://ars.apps.lara.state.mi.us/Home`, `https://ars.apps.lara.state.mi.us/Transaction/RFRTransaction?TransactionID=1306`, `http://www.legislature.mi.gov/Laws/ChapterIndex`
- Landing-page candidates: `https://ars.apps.lara.state.mi.us/AdminCode/AdminCode`

### MT

- Gap category: `corpus_gap_with_landing_candidates`
- Seed URLs: `https://rules.mt.gov`, `https://rules.mt.gov/browse/collections`, `https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74`, `https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/ed446fdb-2d8d-4759-89ac-9cab3b21695c`
- Landing-page candidates: `https://dictionary.cambridge.org/us/dictionary/english/rule`, `https://www.dictionary.com/browse/rule`

### NH

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules`, `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx`, `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/checkrule.aspx`, `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/he-p300.html`
- New substantive URLs: `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/he-p300.html`, `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr100.html`, `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr200.html`
- Landing-page candidates: `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules`, `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx`, `http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/checkrule.aspx`

### RI

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations`, `https://rules.sos.ri.gov/Organizations`, `https://rules.sos.ri.gov/organizations`, `https://rules.sos.ri.gov`
- New substantive URLs: `https://rules.sos.ri.gov/regulations/part/510-00-00-1`, `https://rules.sos.ri.gov/regulations/part/510-00-00-2`
- Landing-page candidates: `https://rules.sos.ri.gov/Organizations`, `https://rules.sos.ri.gov/organizations`, `https://rules.sos.ri.gov/Organizations/agency/100`, `https://rules.sos.ri.gov/Organizations/SubChapter/100-10-00`, `https://rules.sos.ri.gov/Organizations/Chapter/100-10`

### SD

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://rules.sd.gov`, `https://rules.sd.gov/default.aspx`, `https://sdlegislature.gov/Rules/Administrative`

### TX

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.sos.state.tx.us/tac/index.shtml`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=SEARCH_TAC`, `https://www.sos.state.tx.us/texreg/index.shtml`
