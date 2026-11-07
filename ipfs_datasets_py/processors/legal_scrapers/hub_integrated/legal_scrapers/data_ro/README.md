---
pretty_name: Laws of Romania (legislatie.just.ro)
license: other
license_name: romania-legislatie-just
language:
- ro
task_categories:
- text-retrieval
tags:
- legal
- law
- romania
- legislatie-just
- soap
- official-texts
size_categories:
- 1K<n<10K
configs:
- config_name: laws
  data_files: data/laws.parquet
  default: true
- config_name: articles
  data_files: data/articles.parquet
---

# Laws of Romania (legislatie.just.ro)

Research snapshot of official legislation collected from **Portal Legislativ / legislatie.just.ro SOAP FreeWebService**.

**Not legal advice.** Official gazettes / government portals prevail over this corpus.

## Snapshot

| Field | Value |
| --- | --- |
| Snapshot date | 2026-09-03 |
| Coverage | catalog-backed incomplete (SOAP mid-collect / resume snapshot) |
| Source | Portal Legislativ / legislatie.just.ro SOAP FreeWebService |
| Collector | `scrapers/collect_ro.py` |
| Laws / instruments | 7223 |
| Articles | 10 |
| Language | ro |
| Jurisdiction | Romania |
| License | `romania-legislatie-just` |

## Contents

- `data/laws.parquet` — one row per instrument (id, title, full text, ELI,
  dates, status, identifiers, article count, source URL).
- `data/articles.parquet` — one row per article/section (`law_id`, article
  number, title, text, source URL).
- `scrapers/collect_ro.py` — research collector used to build this snapshot.
- `scrapers/common.py` — shared collector helpers.

## License / reuse

Official government / gazette texts; reuse per public-sector terms of the
source portal. This packaging, metadata, and collector script are provided
for research.

This dataset is **not** an official consolidation and is **not legal advice**.
The official source prevails.

## Notes

Official MoJ SOAP FreeWebService snapshot. Collector resumes via existing_ids; SearchResult text may truncate long acts. Not legal advice.
