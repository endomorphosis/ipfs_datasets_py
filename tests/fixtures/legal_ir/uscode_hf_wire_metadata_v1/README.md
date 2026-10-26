---
license: other
pretty_name: "US Code Sparse GraphRAG"
tags:
  - legal
  - us-code
  - graphrag
  - justicedao
  - public-domain-us-government
dataset_info:
- config_name: "publicus-ir-graphrag-v2"
  features:
  - name: "entry_cid"
    dtype: string
  - name: "legal_id"
    dtype: string
  - name: "family"
    dtype: string
  - name: "record_sha256"
    dtype: string
  - name: "record_json"
    dtype: string
  splits:
  - name: "train"
    num_examples: 11
    num_bytes: 4623
configs:
- config_name: "publicus-ir-graphrag-v2"
  default: true
  data_files:
  - split: "train"
    path: ["data/bm25/documents/part-000000.parquet", "data/bm25/postings/part-000000.parquet", "data/corpus/part-000000.parquet", "data/graph/edges/part-000000.parquet", "data/graph/nodes/part-000000.parquet", "data/vectors/centroid-000-part-000000.parquet"]
---

# US Code Sparse GraphRAG

Dataset repository: `justicedao/ipfs_uscode`

## Release profile

- Profile: `publicus-ir-graphrag/v2`
- Pinned source revision: `75cfc5982dc3a6808614cd4eb9b4238f8f9308b8`
- Official release point: `us/pl/118/45`
- Embedding model: `thenlper/gte-small` @ `17e1f347d17fe144873b1201da91788898c639cd`
- Vector space: `gte-small@17e1f347d17fe144873b1201da91788898c639cd:d384:pool=mean:norm=l2`
- Primary key (default config): `entry_cid`

## Dataset configurations

The Hugging Face default is `publicus-ir-graphrag-v2`, an alias for logical configuration `publicus-ir-graphrag/v2`. Only its listed homogeneous Parquet envelopes are advertised. Legacy and recovery files remain available as retained artifacts; their separate streaming configurations are not advertised by this profile. The following inventory describes logical release configurations.

- `publicus-ir-graphrag/v2` (default) — primary key `entry_cid`
  - Default viewer-safe v2 configuration.
  - Excludes recovery JSON and legacy uscode_parquet monoliths.
- `legacy-uscode-parquet/v1` (legacy compatibility) — primary key `ipfs_cid`
  - Explicit deprecation-cycle compatibility path.
  - Must not be the default Dataset Viewer config.
  - Legacy files are retained; packaging never deletes them.
- `recovery-quarantine/v1` (recovery quarantine) — primary key `recovery_id`
  - Quarantine configuration for heterogeneous recovery JSON.
  - Never included in the default config or canonical counts.

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
data/graph/nodes/part-*.parquet
data/graph/edges/part-*.parquet
data/graph/adjacency/out/part-*.parquet
data/graph/adjacency/in/part-*.parquet
indexes/*
reports/admission.json
reports/quality.json
reports/reproducibility.json
reports/lineage.json   # verbose lineage (not control plane)
recovery/...          # quarantine config only
uscode_parquet/...    # legacy compatibility config only
```

## Control plane vs verbose lineage

The control plane consists of `manifest.json`, `release_metadata.json`, routing indexes, and compact admission/quality/reproducibility reports. Verbose per-row source lineage lives only in `reports/lineage.json` and is **not** mixed into Dataset Viewer configs or the release control plane.

## Currentness disclaimer

Acquisition and publication timestamps record when a package was retrieved or sealed; they are not a claim that the codified text is legally current as of wall-clock time. Retrieval output is a research aid and is not a substitute for the official source.

## Limitations

- Retrieval output is a research aid and is not a substitute for the official U.S. Code source.
- Acquisition and publication timestamps are not legal-currentness claims.
- Recovery quarantine rows are excluded from the default config and from corpus/BM25/vector/graph counts until normalized and admitted.
- Legacy and recovery files require direct artifact access until their separate wire schemas/loaders are qualified.

## Integrity

Every artifact is descriptor-bound in `manifest.json` with relative path, media type, row count, byte count, SHA-256, schema identifier, and optional key range. Packaging is additive: legacy files are never deleted by this release builder.

Producer: `uscode_hf_release.py` (`USCIR-031` / `USCIR-G080`).
