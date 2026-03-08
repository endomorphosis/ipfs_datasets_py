# State Admin WebArch Gap Audit

- Generated: `2026-03-08T22:56:37.416961+00:00`
- States audited: **4**
- Per-state workers: **4**
- Max seeds/state: **3**
- Max pages/state: **4**
- Max hops: **1**

## Summary

- States with substantive corpus signal: **2**
- States where probe found substantive pages: **0**
- States where probe found new substantive URLs outside corpus: **0**
- States where probe found only landing-page candidates: **3**
- States blocked mainly by transport/access failures: **2**
- States fetchable but still non-substantive: **1**

## Per-State

| State | Corpus Rows | Corpus Substantive | Probe Success | Usable Success | Probe Substantive | Probe Landing Candidates | New Substantive URLs | Gap Category |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| AZ | 4 | 0 | 2 | 0 | 0 | 0 | 0 | blocked_or_transport_failures |
| IN | 1 | 1 | 4 | 0 | 0 | 4 | 0 | blocked_or_transport_failures |
| TX | 1 | 0 | 4 | 4 | 0 | 2 | 0 | corpus_gap_with_landing_candidates |
| UT | 2 | 1 | 4 | 2 | 0 | 3 | 0 | fetchable_but_non_substantive |

## Priority Gaps

### AZ

- Gap category: `blocked_or_transport_failures`
- Seed URLs: `https://apps.azsos.gov/public_services/Title_00.htm`, `https://apps.azsos.gov/public_services`, `https://legislature.az.gov/rules`

### IN

- Gap category: `blocked_or_transport_failures`
- Seed URLs: `https://iar.iga.in.gov/code/current`, `https://iar.iga.in.gov/code`, `https://iar.iga.in.gov/code/2006`
- Landing-page candidates: `https://iar.iga.in.gov/code/current`, `https://iar.iga.in.gov/code`, `https://iar.iga.in.gov/code/2006`, `https://iar.iga.in.gov/register`

### TX

- Gap category: `corpus_gap_with_landing_candidates`
- Seed URLs: `https://www.sos.state.tx.us/tac/index.shtml`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=SEARCH_TAC`
- Landing-page candidates: `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC`, `https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=SEARCH_TAC`

### UT

- Gap category: `fetchable_but_non_substantive`
- Seed URLs: `https://rules.utah.gov`, `https://adminrules.utah.gov`, `https://adminrules.utah.gov/public/home`
- Landing-page candidates: `https://rules.utah.gov`, `https://adminrules.utah.gov`, `https://rules.utah.gov/march-1-2026-issue-of-the-utah-state-bulletin-is-now-available`
