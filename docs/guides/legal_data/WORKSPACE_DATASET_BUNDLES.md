# Workspace Dataset Bundles

This guide summarizes how to build, package, and inspect workspace datasets in `ipfs_datasets_py`. Workspace datasets are the docket-like artifacts for mixed evidence corpora (email exports, chat logs, drive dumps, and web captures) that need knowledge graphs, BM25, and vector indices ready before deeper analysis.

## What You Get

- A normalized workspace dataset object with documents, collections, and metadata.
- Knowledge graph entities and relationships extracted from the dataset.
- Retrieval artifacts (BM25 + vector indices).
- Optional chain-loadable packaging into Parquet plus IPFS CAR files.

## Build a Workspace Dataset

Use the builder directly when you already have normalized workspace payloads.

```python
from ipfs_datasets_py.processors.legal_data import WorkspaceDatasetBuilder

builder = WorkspaceDatasetBuilder()
dataset = builder.build_from_workspace({
    "workspace_id": "ws-01",
    "workspace_name": "Evidence Workspace",
    "documents": [
        {"id": "doc-1", "title": "Email", "text": "Sample evidence"},
    ],
})
```

## Export a Single-Parquet Bundle

Single-parquet bundles capture the dataset and its indices in one file.

```bash
ipfs-datasets workspace --action export --input-path /path/to/workspace.json \
  --output-parquet /tmp/workspace_bundle.parquet --json
```

## Package Chain-Loadable Bundles

Use packaging when you want the dataset split into chain-loadable artifacts with optional CAR files:

```bash
ipfs-datasets workspace --action package --input-path /path/to/discord_export.json \
  --output-dir /tmp/workspace_bundle --package-name workspace_bundle --json
```

This writes:

- `bundle_manifest.json` with piece metadata
- `parquet/` with dataset slices (documents, graph entities, indices)
- `car/` with optional CAR artifacts when enabled

## Inspect Packaged Bundles

```bash
ipfs-datasets workspace --action package-summary \
  --input-path /tmp/workspace_bundle/bundle_manifest.json --json
```

Use `--action package-inspect` for a richer inspection payload or `--action package-report` to render human-readable summaries.

## Direct Packaging API

```python
from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    package_workspace_dataset,
)

builder = WorkspaceDatasetBuilder()
dataset = builder.build_from_workspace({
    "workspace_id": "ws-01",
    "workspace_name": "Evidence Workspace",
    "documents": [{"id": "doc-1", "title": "Email", "text": "Sample evidence"}],
})

package = package_workspace_dataset(dataset, output_dir="/tmp/workspace_bundle", package_name="workspace_bundle")
print(package["manifest_json_path"])
```

## Related Docs

- `scripts/ops/legal_data/README.md` for ops scripts (export + packaging)
- `docs/guides/CLI_TOOL_MERGE.md` for CLI usage examples
