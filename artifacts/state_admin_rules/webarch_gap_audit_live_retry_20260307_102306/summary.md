# State Admin WebArch Gap Audit

- Generated: `2026-03-07T10:31:44.138242+00:00`
- States audited: **50**
- Per-state workers: **10**
- Max seeds/state: **5**
- Max pages/state: **8**
- Max hops: **1**

## Summary

- States with substantive corpus signal: **40**
- States where probe found substantive pages: **23**
- States where probe found new substantive URLs outside corpus: **10**
- States blocked mainly by transport/access failures: **2**
- States fetchable but still non-substantive: **25**

## Per-State

| State | Corpus Rows | Corpus Substantive | Probe Success | Probe Substantive | New Substantive URLs | Gap Category |
|---|---:|---:|---:|---:|---:|---|
| AK | 6 | 4 | 6 | 0 | 0 | fetchable_but_non_substantive |
| AL | 6 | 0 | 1 | 0 | 0 | fetchable_but_non_substantive |
| AR | 2 | 1 | 5 | 0 | 0 | fetchable_but_non_substantive |
| AZ | 4 | 0 | 0 | 0 | 0 | blocked_or_transport_failures |
| CA | 24 | 24 | 8 | 0 | 0 | fetchable_but_non_substantive |
| CO | 2 | 1 | 8 | 0 | 0 | fetchable_but_non_substantive |
| CT | 1 | 1 | 2 | 0 | 0 | fetchable_but_non_substantive |
| DE | 1 | 1 | 1 | 0 | 0 | fetchable_but_non_substantive |
| FL | 7 | 6 | 7 | 0 | 0 | fetchable_but_non_substantive |
| GA | 9 | 3 | 8 | 0 | 0 | fetchable_but_non_substantive |
| HI | 1 | 1 | 5 | 1 | 0 | has_substantive_signal |
| IA | 3 | 3 | 3 | 0 | 0 | fetchable_but_non_substantive |
| ID | 3 | 3 | 8 | 2 | 0 | has_substantive_signal |
| IL | 3 | 3 | 7 | 1 | 0 | has_substantive_signal |
| IN | 1 | 1 | 6 | 0 | 0 | fetchable_but_non_substantive |
| KS | 1 | 1 | 1 | 1 | 0 | has_substantive_signal |
| KY | 10 | 7 | 5 | 0 | 0 | fetchable_but_non_substantive |
| LA | 1 | 1 | 6 | 1 | 1 | has_substantive_signal |
| MA | 11 | 2 | 8 | 3 | 0 | has_substantive_signal |
| MD | 1 | 0 | 3 | 0 | 0 | fetchable_but_non_substantive |
| ME | 2 | 2 | 6 | 0 | 0 | fetchable_but_non_substantive |
| MI | 2 | 2 | 8 | 1 | 1 | has_substantive_signal |
| MN | 3 | 1 | 3 | 1 | 0 | has_substantive_signal |
| MO | 6 | 6 | 8 | 0 | 0 | fetchable_but_non_substantive |
| MS | 3 | 3 | 6 | 0 | 0 | fetchable_but_non_substantive |
| MT | 1 | 0 | 8 | 2 | 2 | corpus_gap_probe_found_substantive |
| NC | 5 | 4 | 8 | 2 | 0 | has_substantive_signal |
| ND | 3 | 3 | 8 | 2 | 0 | has_substantive_signal |
| NE | 5 | 5 | 8 | 1 | 0 | has_substantive_signal |
| NH | 6 | 0 | 0 | 0 | 0 | blocked_or_transport_failures |
| NJ | 1 | 0 | 2 | 0 | 0 | fetchable_but_non_substantive |
| NM | 2 | 2 | 8 | 4 | 2 | has_substantive_signal |
| NV | 4 | 3 | 7 | 2 | 1 | has_substantive_signal |
| NY | 1 | 1 | 3 | 2 | 1 | has_substantive_signal |
| OH | 4 | 4 | 7 | 1 | 0 | has_substantive_signal |
| OK | 1 | 0 | 7 | 0 | 0 | fetchable_but_non_substantive |
| OR | 3 | 3 | 8 | 0 | 0 | fetchable_but_non_substantive |
| PA | 1 | 1 | 8 | 0 | 0 | fetchable_but_non_substantive |
| RI | 2 | 0 | 7 | 1 | 1 | corpus_gap_probe_found_substantive |
| SC | 3 | 3 | 8 | 1 | 0 | has_substantive_signal |
| SD | 2 | 0 | 4 | 1 | 1 | corpus_gap_probe_found_substantive |
| TN | 12 | 5 | 8 | 0 | 0 | fetchable_but_non_substantive |
| TX | 1 | 0 | 6 | 0 | 0 | fetchable_but_non_substantive |
| UT | 2 | 1 | 7 | 5 | 5 | has_substantive_signal |
| VA | 1 | 1 | 1 | 0 | 0 | fetchable_but_non_substantive |
| VT | 2 | 1 | 8 | 2 | 2 | has_substantive_signal |
| WA | 1 | 1 | 1 | 0 | 0 | fetchable_but_non_substantive |
| WI | 4 | 3 | 8 | 2 | 0 | has_substantive_signal |
| WV | 3 | 3 | 7 | 0 | 0 | fetchable_but_non_substantive |
| WY | 2 | 2 | 2 | 2 | 0 | has_substantive_signal |

## Priority Gaps

### AK

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `http://www.legis.state.ak.us`, `https://alaska.gov`, `https://www.alaska.gov/employeeHome.html`, `https://www.alaska.gov/akdir1.html`

### AL

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.alabamaadministrativecode.state.al.us`, `https://www.sos.alabama.gov/alabama-administrative-code`, `https://legislature.al.gov/rules`, `https://legislature.al.gov/regulations`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

### AR

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.arkleg.state.ar.us/Home/FTPDocument?path=%2FBills%2FVetoBook.pdf`, `https://www.arkleg.state.ar.us/Committees/Detail?code=005&ddBienniumSession=2025%2F2026F`

### AZ

- Gap category: `blocked_or_transport_failures`
- Seed URLs: `https://apps.azsos.gov/public_services/Title_00.htm`, `https://apps.azsos.gov/public_services`, `https://legislature.az.gov/rules`, `https://legislature.az.gov/regulations`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

### CA

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://leginfo.legislature.ca.gov/faces/codedisplayexpand.xhtml?tocCode=BPC`, `https://leginfo.legislature.ca.gov/faces/codedisplayexpand.xhtml?tocCode=CIV`, `https://leginfo.legislature.ca.gov/faces/codedisplayexpand.xhtml?tocCode=CORP`, `https://leginfo.legislature.ca.gov/faces/codedisplayexpand.xhtml?tocCode=EDC`

### CO

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://leg.colorado.gov`, `https://content.leg.colorado.gov/publication-search?search_api_fulltext=crs`

### CT

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `http://web.archive.org/web/20250101000000/http://www.cga.ct.gov/current/pub/titles.htm`

### DE

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://delcode.delaware.gov/title1/c001/index.html`

### FL

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `http://www.leg.state.fl.us/Statutes`, `http://www.leg.state.fl.us/cgi-bin/View_Page.pl?File=index_css.html&Directory=committees/joint/JAPC/&Tab=committees`, `http://www.leg.state.fl.us/index.cfm?Tab=statutes&submenu=-1`, `http://www.leg.state.fl.us/index.cfm?Mode=View%20Statutes&Submenu=1&Tab=statutes`

### GA

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://rules.sos.ga.gov/gac`, `https://rules.sos.ga.gov`, `https://rules.sos.ga.gov/gac/90`, `https://dol.georgia.gov/individuals/job-search-assistance`

### IA

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.legis.iowa.gov`, `https://www.legis.iowa.gov/law/administrativeRules/agencies`, `https://www.legis.iowa.gov/law`

### IN

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://iar.iga.in.gov/code`, `https://iar.iga.in.gov/iac`, `https://iga.in.gov/legislative/laws/iac`, `https://www.in.gov/core/index.html`

### KY

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://legislature.ky.gov`, `https://legislature.ky.gov/Law/kar/Pages/default.aspx`, `https://legislature.ky.gov/Law/kar/Pages/EmergencyRegs.aspx`, `https://www.kentucky.gov/government/Pages/agency.aspx`

### MD

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://mgaleg.maryland.gov/mgawebsite/Laws/Statutes`

### ME

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `http://legislature.maine.gov`, `http://legislature.maine.gov/senate`

### MO

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://revisor.mo.gov`, `https://revisor.mo.gov/main/Home.aspx`, `https://revisor.mo.gov/main/OneChapter.aspx?chapter=195`, `https://revisor.mo.gov/main/OneChapter.aspx?chapter=293`

### MS

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.sos.ms.gov/adminsearch/Pages/default.aspx`, `https://www.sos.ms.gov/adminsearch`, `https://web.archive.org/web/19980110154920/http://billstatus.ls.state.ms.us/1997/history/HB/HB0026.htm`, `https://web.archive.org/web/19980110154920/http://billstatus.ls.state.ms.us/1997/history/HB/HB0027.htm`
- Blocked examples: `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`, `common_crawl_search_engine error: FileNotFoundError: Parquet root does not exist: /storage/ccindex_parquet; playwright e`

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

### OR

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://secure.sos.state.or.us/oard/displayChapterRules.action?selectedChapter=137`, `https://www.oregonlegislature.gov/bills_laws/ors/ors001.html`, `https://www.oregonlegislature.gov/bills_laws/Pages/ORS.aspx`

### PA

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.legis.state.pa.us`, `https://www.legis.state.pa.us/rules`, `https://www.legis.state.pa.us/regulations`, `https://www.legis.state.pa.us/administrative-code`

### RI

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations`, `https://rules.sos.ri.gov`, `https://web.archive.org/web/20121004042026/http:/webserver.rilin.state.ri.us/Statutes/TITLE3/3-8/INDEX.HTM`, `https://web.archive.org/web/20121004042026/http:/webserver.rilin.state.ri.us/Statutes/TITLE4/4-13.1/INDEX.HTM`
- New substantive URLs: `https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations/building-and-fire-codes`

### SD

- Gap category: `corpus_gap_probe_found_substantive`
- Seed URLs: `https://rules.sd.gov`, `https://rules.sd.gov/default.aspx`, `https://sdlegislature.gov/Rules/Administrative`
- New substantive URLs: `https://sdlegislature.gov/Rules/Administrative`

### TN

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://publications.tnsosfiles.com/rules`, `https://www.tn.gov/sos/rules-and-regulations.html`, `https://www.tn.gov`, `https://sos.tn.gov/civics/guides/statehood-and-state-history`

### TX

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://www.sos.state.tx.us/tac/index.shtml`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=SEARCH_TAC`, `https://www.sos.state.tx.us/texreg/index.shtml`

### VA

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://law.lis.virginia.gov`

### WA

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32.030`

### WV

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://code.wvlegislature.gov`, `https://code.wvlegislature.gov/11-8-12`, `https://code.wvlegislature.gov/signed_bills/2025/2025-RS-SB10-SUB1 ENR_signed.pdf`
