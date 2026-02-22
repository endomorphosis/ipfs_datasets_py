# Dataset Tools

Core MCP tools for loading, saving, processing, and transforming datasets. These tools are thin
wrappers around `ipfs_datasets_py.core_operations.*` — all business logic lives in the core module.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `load_dataset.py` | `load_dataset()` | Load a dataset from HuggingFace Hub, local path, or IPFS CID |
| `save_dataset.py` | `save_dataset()` | Save a dataset to disk, IPFS, or a remote destination |
| `convert_dataset_format.py` | `convert_dataset_format()` | Convert between dataset formats (Parquet, JSON, CSV, Arrow) |
| `process_dataset.py` | `process_dataset()` | Apply transformations: filter, map, shuffle, select columns |
| `text_to_fol.py` | `text_to_fol()` | Convert natural-language text to First-Order Logic formulas |
| `legal_text_to_deontic.py` | `legal_text_to_deontic()` | Convert legal text to Temporal Deontic Logic (TDFOL) formulas |
| `dataset_tools_claudes.py` | Multiple | Extended dataset utilities (Claude-assisted operations) |

## Usage

### Load a dataset

```python
from ipfs_datasets_py.mcp_server.tools.dataset_tools import load_dataset

result = await load_dataset(
    source="squad",            # HuggingFace Hub name, local path, or IPFS CID
    split="train",             # Optional: "train", "test", "validation"
    max_rows=1000,             # Optional: limit rows for testing
    output_format="dict"       # "dict" | "json" | "arrow"
)
# Returns: {"status": "success", "dataset": {...}, "metadata": {...}}
```

### Save a dataset

```python
from ipfs_datasets_py.mcp_server.tools.dataset_tools import save_dataset

result = await save_dataset(
    dataset=my_dataset,
    output_path="/path/to/output",
    format="parquet",          # "parquet" | "json" | "csv" | "arrow"
    pin_to_ipfs=True           # Optional: also pin to IPFS
)
```

### Convert format

```python
from ipfs_datasets_py.mcp_server.tools.dataset_tools import convert_dataset_format

result = await convert_dataset_format(
    input_path="/data/input.json",
    output_path="/data/output.parquet",
    input_format="json",
    output_format="parquet",
    compression="snappy"
)
```

### Text to First-Order Logic

```python
from ipfs_datasets_py.mcp_server.tools.dataset_tools import text_to_fol

result = await text_to_fol(
    text="All mammals are warm-blooded. Dogs are mammals.",
    output_format="prolog"     # "prolog" | "tptp" | "smtlib"
)
# Returns: {"formulas": ["∀x(mammal(x) → warm_blooded(x))", "mammal(dog)"], ...}
```

## Core Module

All business logic delegates to:
- `ipfs_datasets_py.core_operations.dataset_loader.DatasetLoader`
- `ipfs_datasets_py.core_operations.dataset_saver.DatasetSaver`
- `ipfs_datasets_py.logic.fol.convert_text_to_fol`
- `ipfs_datasets_py.logic.tools.legal_text_to_deontic`

## Dependencies

**Required:**
- Standard library: `json`, `os`, `pathlib`

**Optional (graceful degradation if missing):**
- `datasets` (HuggingFace) — for Hub dataset loading
- `pyarrow` / `pandas` — for Parquet/Arrow conversion
- `ipfs_datasets_py` — for IPFS-backed storage

## Status

| Tool | Status |
|------|--------|
| `load_dataset` | ✅ Production ready |
| `save_dataset` | ✅ Production ready |
| `convert_dataset_format` | ✅ Production ready |
| `process_dataset` | ✅ Production ready |
| `text_to_fol` | ✅ Production ready |
| `legal_text_to_deontic` | ✅ Production ready |
