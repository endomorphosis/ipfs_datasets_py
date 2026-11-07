---
pretty_name: Laws of Slovenia (Uradni list RS)
license: other
license_name: slovenia-ul-official
language:
- sl
task_categories:
- text-retrieval
tags:
- legal
- law
- slovenia
- uradni-list
- gazette
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

# Laws of Slovenia (Uradni list RS)

Research snapshot of official legislation collected from **Uradni list Republike Slovenije (uradni-list.si)**.

**Not legal advice.** Official gazettes / government portals prevail over this corpus.

## Snapshot

| Field | Value |
| --- | --- |
| Snapshot date | 2026-09-03 |
| Coverage | catalog-backed incomplete (Uradni list issue TOC harvest) |
| Source | Uradni list Republike Slovenije (uradni-list.si) |
| Collector | `scrapers/collect_si.py` |
| Laws / instruments | 1661 |
| Articles | 12 |
| Language | sl |
| Jurisdiction | Slovenia |
| License | `slovenia-ul-official` |

## Contents

- `data/laws.parquet` — one row per instrument (id, title, full text, ELI,
  dates, status, identifiers, article count, source URL).
- `data/articles.parquet` — one row per article/section (`law_id`, article
  number, title, text, source URL).
- `scrapers/collect_si.py` — research collector used to build this snapshot.
- `scrapers/common.py` — shared collector helpers.

## License / reuse

Official government / gazette texts; reuse per public-sector terms of the
source portal. This packaging, metadata, and collector script are provided
for research.

This dataset is **not** an official consolidation and is **not legal advice**.
The official source prevails.

## Notes

Official Uradni list RS HTML. PISRS REST token-gated (not used). Partial issue-TOC harvest. Not legal advice.
