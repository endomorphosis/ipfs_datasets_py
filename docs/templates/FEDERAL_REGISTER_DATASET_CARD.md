---
license: other
pretty_name: "Federal Register Sparse GraphRAG"
tags:
  - legal
  - federal-register
  - graphrag
  - justicedao
  - public-domain-us-government
configs:
- config_name: "federal-register-ir-graphrag/v2"
  data_files:
  - split: "train"
    path: "data/**/*.parquet"
- config_name: "legacy-federal-register-parquet/v1"
  data_files:
  - split: "train"
    path: "federal_register.parquet"
- config_name: "recovery"
  data_files:
  - split: "train"
    path: "recovery/**/*.json"
- config_name: "quarantine"
  data_files:
  - split: "train"
    path: "quarantine/**/*.json"
---

# Federal Register Sparse GraphRAG

Dataset repository: `justicedao/ipfs_federal_register`

## Release profile

- Profile: `federal-register-ir-graphrag/v2`
- Pinned source revision: `720668ae016cc400916dda884c9005e03618edfa`
- Observation cutoff: `2026-08-10T00:00:00Z`
- Embedding model: `thenlper/gte-small` @ `17e1f347d17fe144873b1201da91788898c639cd`
- Vector space: `gte-small@17e1f347d17fe144873b1201da91788898c639cd:d384:pool=mean:norm=l2`
- Primary key (default config): `entry_cid`
- Default configuration: `federal-register-ir-graphrag/v2` (Viewer-safe v2)
- Previous public pin (rollback): `720668ae016cc400916dda884c9005e03618edfa`

## Dataset configurations

The **default** configuration is Viewer-safe v2 Federal Register documents only. Recovery JSON, quarantine JSON, and legacy federal_register.parquet / JSON-LD / FAISS files are advertised as separate named configs and never contaminate the default Dataset Viewer schema.

- `federal-register-ir-graphrag/v2` (default v2) — primary key `entry_cid`
  - Viewer-safe default v2 Federal Register configuration.
  - Cutoff-relative official Federal Register documents with full-text dispositions.
  - Excludes recovery, quarantine, and legacy root-level Parquet/JSON-LD/FAISS rows.
- `legacy-federal-register-parquet/v1` (legacy compatibility) — primary key `document_number`
  - Explicit deprecation-cycle compatibility path for federal_register.parquet.
  - Must not be the default Dataset Viewer config.
  - Legacy files are retained; packaging never deletes them.
- `recovery` (recovery) — primary key `recovery_id`
  - Recovery records that cannot enter canonical default counts.
  - Never included in the default config or Viewer-safe v2 gate.
- `quarantine` (quarantine) — primary key `recovery_id`
  - Quarantined or rejected rows excluded from the Viewer default split.
  - Unknown or prohibited rights stay out of the default v2 config.

## Artifact layout

```text
README.md
manifest.json
release_metadata.json
dataset_configs.json
dataset_infos.json
data/corpus/year_month=*/document_type=*/part-*.parquet
data/bm25/documents/year_month=*/document_type=*/part-*.parquet
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
federal_register.parquet  # legacy compatibility config only
```

## Control plane vs verbose lineage

The control plane consists of `manifest.json`, `release_metadata.json`, routing indexes, source-receipt descriptors, and compact admission/quality/reproducibility reports. Verbose per-row source lineage lives only in `reports/lineage.json` and is **not** mixed into Dataset Viewer configs or the release control plane.

## Source-scope rights summary

This additive fixture assembly binds the LCR-078/LCR-079/LCR-083 source-rights compliance receipt and cannot authorize publication.

- Receipt path: `docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json`
- Source-rights receipt digest: `46ef76257b938dc532311207bcbe97f12bc5b9fdf587b370b4273e1b912969ee`
- Source-rights catalog digest: `3ba1d10b30598c2145ee0dfa62db42d69d2d664578fce90d5c4ed756ac742a4b`
- Admitted source-scope records: 52
- Unknown or prohibited rights cannot enter the default v2 release.
- Fixture receipts set `authorizing_for_publication=false`.

## Route bounds

- At most 4096 rows per physical shard.
- At most 4096 BM25 posting pointers per cell.
- At most 4096 adjacency pointers per page.
- At most 8192 vectors and 2 shards per centroid.
- Model token ceiling is 512; it is not a shard bound.

## Currentness disclaimer

Federal Register completeness is cutoff-relative. Acquisition and publication timestamps record when a package was retrieved or sealed; they are not a claim that the daily register is permanently current as of wall-clock time. Retrieval output is a research aid and is not a substitute for the official source.

## Limitations

- Retrieval output is a research aid and is not a substitute for the official Federal Register or GovInfo publications.
- Acquisition and publication timestamps are not legal-currentness claims.
- Recovery and quarantine rows are excluded from the default v2 config and from corpus/BM25/vector/graph counts until admitted.
- Unknown or prohibited source-rights dispositions cannot enter the default Viewer config.
- Legacy federal_register.parquet / JSON-LD / FAISS remains available only through the explicit compatibility configuration for one deprecation cycle.

## Integrity

Every artifact is descriptor-bound in `manifest.json` with relative path, media type, row count, byte count, SHA-256, schema identifier, and optional key range. The manifest also binds corpus, BM25, vectors, centroids, the vector locator, the legal graph, two-way adjacency, recovery, source receipts, the pinned model revision, route bounds, old-pin rollback metadata, and the source-rights receipt digest.

Producer: `federal_register_hf_release.py` (`LCR-062` / `LCR-G130`).
