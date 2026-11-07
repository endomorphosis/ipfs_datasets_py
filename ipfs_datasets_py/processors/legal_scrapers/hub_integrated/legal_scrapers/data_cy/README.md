---
pretty_name: Laws of Cyprus (GPO gazette)
license: other
license_name: cyprus-gpo-official
language:
- el
task_categories:
- text-retrieval
tags:
- legal
- law
- cyprus
- gpo
- gazette
- official-texts
size_categories:
- n<1K
configs:
- config_name: laws
  data_files: data/laws.parquet
  default: true
- config_name: articles
  data_files: data/articles.parquet
---

# Laws of Cyprus (GPO gazette)

Research snapshot of official legislation collected from **Cyprus Government Printing Office gazette (mof.gov.cy)**.

**Not legal advice.** Official gazettes / government portals prevail over this corpus.

## Snapshot

| Field | Value |
| --- | --- |
| Snapshot date | 2026-09-03 |
| Coverage | catalog-backed incomplete (GPO HTML; PDFs not extracted; legislation.gov.cy NXDOMAIN; cylaw unused) |
| Source | Cyprus Government Printing Office gazette (mof.gov.cy) |
| Collector | `scrapers/collect_cy.py` |
| Laws / instruments | 19 |
| Articles | 0 |
| Language | el |
| Jurisdiction | Cyprus |
| License | `cyprus-gpo-official` |

## Contents

- `data/laws.parquet` — one row per instrument (id, title, full text, ELI,
  dates, status, identifiers, article count, source URL).
- `data/articles.parquet` — one row per article/section (`law_id`, article
  number, title, text, source URL).
- `scrapers/collect_cy.py` — research collector used to build this snapshot.
- `scrapers/common.py` — shared collector helpers.

## License / reuse

Official government / gazette texts; reuse per public-sector terms of the
source portal. This packaging, metadata, and collector script are provided
for research.

This dataset is **not** an official consolidation and is **not legal advice**.
The official source prevails.

## Notes

Official GPO HTML harvest. PDF gazette bodies not extracted. legislation.gov.cy NXDOMAIN. Not legal advice.
