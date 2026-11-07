---
pretty_name: Laws of Italy (Normattiva OpenData)
license: other
license_name: italy-normattiva-opendata
language:
- it
task_categories:
- text-retrieval
tags:
- legal
- law
- italy
- normattiva
- opendata
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

# Laws of Italy (Normattiva OpenData)

Research snapshot of official legislation collected from **Normattiva OpenData (dati.normattiva.it / api.normattiva.it)**.

**Not legal advice.** Official gazettes / government portals prevail over this corpus.

## Snapshot

| Field | Value |
| --- | --- |
| Snapshot date | 2026-09-03 |
| Coverage | catalog-backed incomplete (Normattiva OpenData mid-collect) |
| Source | Normattiva OpenData (dati.normattiva.it / api.normattiva.it) |
| Collector | `scrapers/collect_it.py` |
| Laws / instruments | 1344 |
| Articles | 0 |
| Language | it |
| Jurisdiction | Italy |
| License | `italy-normattiva-opendata` |

## Contents

- `data/laws.parquet` — one row per instrument (id, title, full text, ELI,
  dates, status, identifiers, article count, source URL).
- `data/articles.parquet` — one row per article/section (`law_id`, article
  number, title, text, source URL).
- `scrapers/collect_it.py` — research collector used to build this snapshot.
- `scrapers/common.py` — shared collector helpers.

## License / reuse

Official government / gazette texts; reuse per public-sector terms of the
source portal. This packaging, metadata, and collector script are provided
for research.

This dataset is **not** an official consolidation and is **not legal advice**.
The official source prevails.

## Notes

Official Normattiva OpenData ricerca/avanzata + dettaglio-atto. Catalog ~48k discovered; this snapshot is partial fetch. Not legal advice.
