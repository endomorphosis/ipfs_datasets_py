---
license: other
configs:
- config_name: articles
  data_files:
  - split: train
    path: data/articles*.parquet
  default: true
- config_name: laws
  data_files:
  - split: train
    path: data/laws*.parquet
pretty_name: ipfs_namibia_laws
tags:
- legal
- law
---

# Namibia Laws

Legal corpus for Namibia from the ipfs_datasets_py legal scrapers (endomorphosis).

- Instruments: 530
- Last updated: 2026-09-16
- Source: official gazettes and legal portals; see source_url per record.
- Schema: id, title, text, source_url, source_type, jurisdiction, country, language, eli, date, retrieved_at, license, law_status, identifiers.
