# File Detection Tools

MCP tools for detecting file types using multiple strategies: magic bytes, MIME type inference,
extension mapping, and combined analysis.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `detect_file_type.py` | `detect_file_type()` | Detect the type of a single file using a specified strategy |
| `batch_detect_file_types.py` | `batch_detect_file_types()` | Detect types for multiple files in batch |
| `analyze_detection_accuracy.py` | `analyze_detection_accuracy()` | Compare detection strategies on a labelled file set |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.file_detection_tools import (
    detect_file_type, batch_detect_file_types
)

# Detect a single file
result = await detect_file_type(
    file_path="/data/unknown_file",
    strategy="combined"    # "magic" | "extension" | "mime" | "combined"
)
# Returns: {"mime_type": "application/pdf", "extension": ".pdf", "confidence": 0.99}

# Batch detect
results = await batch_detect_file_types(
    directory="/data/uploads/",
    recursive=True,
    output_format="json"
)
```

## Core Module

- `ipfs_datasets_py.processors` — file detection logic

## Dependencies

- `python-magic` — magic byte detection (optional; falls back to extension)

## Status

| Tool | Status |
|------|--------|
| `detect_file_type` | ✅ Production ready |
| `batch_detect_file_types` | ✅ Production ready |
| `analyze_detection_accuracy` | ✅ Production ready |
