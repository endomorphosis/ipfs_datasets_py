---
pretty_name: Laws of Bulgaria (State Gazette)
license: other
license_name: bulgaria-dv-official
language:
- bg
task_categories:
- text-retrieval
tags:
- legal
- law
- bulgaria
- state-gazette
- dv
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

# Laws of Bulgaria (State Gazette)

Research snapshot of official legislation collected from **Държавен вестник / State Gazette (dv.parliament.bg)**.

**Not legal advice.** Official gazettes / government portals prevail over this corpus.

## Snapshot

| Field | Value |
| --- | --- |
| Snapshot date | 2026-09-03 |
| Coverage | shard (live dv.parliament.bg TLS EOF; Wayback/CC archive fallback) |
| Source | Държавен вестник / State Gazette (dv.parliament.bg) |
| Collector | `scrapers/collect_bg.py` |
| Laws / instruments | 16 |
| Articles | 236 |
| Language | bg |
| Jurisdiction | Bulgaria |
| License | `bulgaria-dv-official` |

## Contents

- `data/laws.parquet` — one row per instrument (id, title, full text, ELI,
  dates, status, identifiers, article count, source URL).
- `data/articles.parquet` — one row per article/section (`law_id`, article
  number, title, text, source URL).
- `scrapers/collect_bg.py` — research collector used to build this snapshot.
- `scrapers/common.py` — shared collector helpers.

## License / reuse

Official government / gazette texts; reuse per public-sector terms of the
source portal. This packaging, metadata, and collector script are provided
for research.

This dataset is **not** an official consolidation and is **not legal advice**.
The official source prevails.

## Notes

Live State Gazette SSL handshake fails (UNEXPECTED_EOF). Archive fallback shard. Not legal advice.
