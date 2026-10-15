---
license: other
configs:
- config_name: autoformal_uscode
  data_files:
  - split: train
    path: autoformal/uscode/kg-logic-index.parquet
  default: true
pretty_name: uscode-autoformal-entity-cache
tags:
- legal
- law
---


## Scrapers & normalizer
The scrapers and normalizer that produced this dataset are published in [justicedao/world_law_scrapers](https://huggingface.co/datasets/justicedao/world_law_scrapers) (canonical schema: `law_id, id, title, text, source_url, document_number, article_number, record_type, metadata_json`, matching endomorphosis/ipfs_malta_laws).
