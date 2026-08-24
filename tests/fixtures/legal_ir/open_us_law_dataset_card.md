---
license: other
pretty_name: "Open US Law Sparse GraphRAG"
tags:
  - legal
  - state-statutes
  - graphrag
  - justicedao
  - open-us-law
  - exact-51
configs:
- config_name: "state_statutes_exact_51"
  data_files:
  - split: "train"
    path: "data/**/*.parquet"
- config_name: "federal_uscode"
  data_files:
  - split: "train"
    path: "configs/federal_uscode/**/*.parquet"
- config_name: "puerto_rico"
  data_files:
  - split: "train"
    path: "configs/puerto_rico/**/*.parquet"
- config_name: "constitutions"
  data_files:
  - split: "train"
    path: "configs/constitutions/**/*.parquet"
- config_name: "historical"
  data_files:
  - split: "train"
    path: "configs/historical/**/*.parquet"
- config_name: "recovery"
  data_files:
  - split: "train"
    path: "recovery/**/*.json"
- config_name: "quarantine"
  data_files:
  - split: "train"
    path: "quarantine/**/*.json"
---

# Open US Law Sparse GraphRAG

Dataset repository: `justicedao/open-us-law-sparse-graphrag`
Source bucket: `justicedao/open-us-law-bucket`

## Release profile

- Profile: `open-us-law-sparse-graphrag/v1`
- Pinned source revision: `7c1e4a90b2d65f83e0a91c4d6b7e8f0123456789abcdef0123456789abcdef01`
- Embedding model: `thenlper/gte-small` @ `17e1f347d17fe144873b1201da91788898c639cd`
- Vector space: `gte-small@17e1f347d17fe144873b1201da91788898c639cd:d384:pool=mean:norm=l2`
- Primary key (default config): `entry_cid`
- Default configuration: `state_statutes_exact_51` (Viewer-safe exact-51)
- Required jurisdictions: 51 (50 states plus DC)

## Dataset configurations

The **default** configuration is Viewer-safe exact-51 state and DC statutes only. Recovery JSON, quarantine JSON, federal US Code, Puerto Rico, constitutions, and historical rows are advertised as separate named configs and never contaminate the default Dataset Viewer schema or the exact-51 gate.

- `state_statutes_exact_51` (default exact-51) — primary key `entry_cid`
  - Viewer-safe default exact-51 configuration.
  - Current official statutes for exactly the 50 states plus DC.
  - Excludes recovery, quarantine, federal US Code, Puerto Rico, constitutions, and historical rows.
- `federal_uscode` (named non-default) — primary key `entry_cid`
  - Federal United States Code rows. Useful corpus; never default exact-51.
  - Must not be the default Dataset Viewer config.
- `puerto_rico` (named non-default) — primary key `entry_cid`
  - Puerto Rico statutory rows. Explicit non-default configuration.
  - Must not be the default Dataset Viewer config.
- `constitutions` (named non-default) — primary key `entry_cid`
  - Federal, state, DC, and territorial constitution rows.
  - Must not be the default Dataset Viewer config.
- `historical` (named non-default) — primary key `entry_cid`
  - Superseded, repealed, or otherwise non-current statute versions.
  - Must not be the default Dataset Viewer config.
- `recovery` (recovery) — primary key `recovery_id`
  - Recovery records that cannot enter canonical default counts.
  - Never included in the default config or exact-51 gate.
- `quarantine` (quarantine) — primary key `recovery_id`
  - Quarantined or rejected rows excluded from the Viewer default split.
  - Never included in the default config or exact-51 gate.

## Artifact layout

```text
README.md
manifest.json
release_metadata.json
dataset_configs.json
dataset_infos.json
data/corpus/part-*.parquet
data/bm25/documents/part-*.parquet
data/bm25/postings/part-*.parquet
data/vectors/centroid-*-part-*.parquet
data/vectors/centroids/part-*.parquet
data/vectors/locator/part-*.parquet
data/graph/nodes/part-*.parquet
data/graph/edges/part-*.parquet
data/graph/adjacency/out/part-*.parquet
data/graph/adjacency/in/part-*.parquet
indexes/*
receipts/source/*
reports/admission.json
reports/quality.json
reports/reproducibility.json
reports/lineage.json   # verbose lineage (not control plane)
recovery/...          # recovery config only
quarantine/...        # quarantine config only
configs/federal_uscode/...
configs/puerto_rico/...
configs/constitutions/...
configs/historical/...
```

## Control plane vs verbose lineage

The control plane consists of `manifest.json`, `release_metadata.json`, routing indexes, source-receipt descriptors, and compact admission/quality/reproducibility reports. Verbose per-row source lineage lives only in `reports/lineage.json` and is **not** mixed into Dataset Viewer configs or the release control plane.

## Route bounds

- At most 4096 rows per physical shard.
- At most 4096 BM25 posting pointers per cell.
- At most 4096 adjacency pointers per page.
- At most 8192 vectors and 2 shards per centroid.
- Model token ceiling is 512; it is not a shard bound.

## Currentness disclaimer

This release is a research retrieval aid. Observation times, edition pins, and acquisition receipts are not legal-currentness claims. Official state and District of Columbia publications remain the authority.

## Limitations

- Retrieval output is a research aid and is not a substitute for official state or District of Columbia publications.
- Acquisition and publication timestamps are not legal-currentness claims.
- Recovery and quarantine rows are excluded from the default exact-51 config and from corpus/BM25/vector/graph counts until admitted.
- Federal US Code, Puerto Rico, constitutions, and historical rows are explicit non-default configurations and cannot satisfy the exact-51 gate.

## Integrity

Every artifact is descriptor-bound in `manifest.json` with relative path, media type, row count, byte count, SHA-256, schema identifier, and optional key range. The manifest also binds corpus, BM25, vectors, centroids, the vector locator, the legal graph, two-way adjacency, recovery, source receipts, the pinned model revision, and route bounds.

Producer: `open_us_law_hf_release.py` (`OUL-032` / `OUL-G040`).
