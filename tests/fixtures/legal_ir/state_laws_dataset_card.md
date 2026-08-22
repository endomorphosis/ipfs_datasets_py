---
license: other
pretty_name: "State Laws Sparse GraphRAG"
tags:
  - legal
  - state-statutes
  - graphrag
  - justicedao
  - exact-51
  - state-laws
configs:
- config_name: "state_statutes_exact_51"
  data_files:
  - split: "train"
    path: "data/**/*.parquet"
- config_name: "legacy-state-parquet/v1"
  data_files:
  - split: "train"
    path: "STATE-*.parquet"
- config_name: "recovery"
  data_files:
  - split: "train"
    path: "recovery/**/*.json"
- config_name: "quarantine"
  data_files:
  - split: "train"
    path: "quarantine/**/*.json"
---

# State Laws Sparse GraphRAG

Dataset repository: `justicedao/ipfs_state_laws`

## Release profile

- Profile: `state-laws-ir-graphrag/v2`
- Pinned source revision: `42f0546acc7c6cd55627eaf51fb820d5613b9021`
- Embedding model: `thenlper/gte-small` @ `17e1f347d17fe144873b1201da91788898c639cd`
- Vector space: `gte-small@17e1f347d17fe144873b1201da91788898c639cd:d384:pool=mean:norm=l2`
- Primary key (default config): `entry_cid`
- Default configuration: `state_statutes_exact_51` (Viewer-safe exact-51)
- Required jurisdictions: 51 (50 states plus DC)

## Dataset configurations

The **default** configuration is Viewer-safe exact-51 state and DC statutes only. Recovery JSON, quarantine JSON, and legacy STATE-*.parquet files are advertised as separate named configs and never contaminate the default Dataset Viewer schema or the exact-51 gate.

- `state_statutes_exact_51` (default exact-51) — primary key `entry_cid`
  - Viewer-safe default exact-51 configuration.
  - Current official statutes for exactly the 50 states plus DC.
  - Excludes recovery, quarantine, and legacy STATE-*.parquet rows.
- `legacy-state-parquet/v1` (legacy compatibility) — primary key `ipfs_cid`
  - Explicit deprecation-cycle compatibility path for STATE-XX.parquet.
  - Must not be the default Dataset Viewer config.
  - Legacy files are retained; packaging never deletes them.
- `recovery` (recovery) — primary key `recovery_id`
  - Recovery records that cannot enter canonical default counts.
  - Never included in the default config or exact-51 gate.
- `quarantine` (quarantine) — primary key `recovery_id`
  - Quarantined or rejected rows excluded from the Viewer default split.
  - Unknown or prohibited rights stay out of the default exact-51 config.

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
STATE-*.parquet       # legacy compatibility config only
```

## Control plane vs verbose lineage

The control plane consists of `manifest.json`, `release_metadata.json`, routing indexes, source-receipt descriptors, and compact admission/quality/reproducibility reports. Verbose per-row source lineage lives only in `reports/lineage.json` and is **not** mixed into Dataset Viewer configs or the release control plane.

## Source-scope rights summary

This additive fixture assembly binds the LCR-078/LCR-079/LCR-083 source-rights compliance receipt and cannot authorize publication.

- Receipt path: `docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json`
- Source-rights receipt digest: `46ef76257b938dc532311207bcbe97f12bc5b9fdf587b370b4273e1b912969ee`
- Source-rights catalog digest: `3ba1d10b30598c2145ee0dfa62db42d69d2d664578fce90d5c4ed756ac742a4b`
- Admitted source-scope records: 52
- Unknown or prohibited rights cannot enter the default exact-51 release.
- Fixture receipts set `authorizing_for_publication=false`.

## Route bounds

- At most 4096 rows per physical shard.
- At most 4096 BM25 posting pointers per cell.
- At most 4096 adjacency pointers per page.
- At most 8192 vectors and 2 shards per centroid.
- Model token ceiling is 512; it is not a shard bound.

## Currentness disclaimer

Acquisition and publication timestamps record when a package was retrieved or sealed; they are not a claim that the codified text is legally current as of wall-clock time. Retrieval output is a research aid and is not a substitute for the official source.

## Limitations

- Retrieval output is a research aid and is not a substitute for official state or District of Columbia publications.
- Acquisition and publication timestamps are not legal-currentness claims.
- Recovery and quarantine rows are excluded from the default exact-51 config and from corpus/BM25/vector/graph counts until admitted.
- Unknown or prohibited source-rights dispositions cannot enter the default exact-51 Viewer config.
- Legacy STATE-*.parquet remains available only through the explicit compatibility configuration for one deprecation cycle.

## Integrity

Every artifact is descriptor-bound in `manifest.json` with relative path, media type, row count, byte count, SHA-256, schema identifier, and optional key range. The manifest also binds corpus, BM25, vectors, centroids, the vector locator, the legal graph, two-way adjacency, recovery, source receipts, the pinned model revision, route bounds, and the source-rights receipt digest.

Producer: `state_laws_hf_release.py` (`LCR-032` / `LCR-G040`).
