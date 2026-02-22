# File Converter Tools

MCP tools for converting files between formats, downloading from URLs, extracting archives,
extracting knowledge graphs, generating embeddings, and summarising content. Thin wrappers
around the `file_converter` package.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `convert_file.py` | `convert_file()` | Convert a file or URL to text (HTML→text, PDF→text, DOCX→text, etc.) |
| `batch_convert.py` | `batch_convert()` | Batch convert multiple files or URLs |
| `download_url.py` | `download_url()` | Download a file from a URL to local storage |
| `extract_archive.py` | `extract_archive()` | Extract ZIP, TAR, GZ, 7Z archives |
| `extract_knowledge_graph.py` | `extract_knowledge_graph()` | Extract entities and relationships from a file |
| `file_info.py` | `file_info()` | Get MIME type, size, encoding, and metadata about a file |
| `generate_embeddings.py` | `generate_embeddings_from_file()` | Generate vector embeddings from file contents |
| `generate_summary.py` | `generate_summary()` | Generate a text summary of a file using an LLM |

## Usage

### Convert a file to text

```python
from ipfs_datasets_py.mcp_server.tools.file_converter_tools import convert_file

result = await convert_file(
    input_path="/data/document.pdf",
    output_format="text",
    extract_images=False
)
# Returns: {"text": "...", "page_count": 12, "encoding": "utf-8"}
```

### Batch convert

```python
from ipfs_datasets_py.mcp_server.tools.file_converter_tools import batch_convert

result = await batch_convert(
    inputs=["/data/a.pdf", "/data/b.docx", "https://example.com/c.html"],
    output_dir="/data/converted/",
    output_format="text",
    parallel_workers=4
)
```

### Extract knowledge graph

```python
from ipfs_datasets_py.mcp_server.tools.file_converter_tools import extract_knowledge_graph

kg = await extract_knowledge_graph(
    input_path="/data/research_paper.pdf",
    entity_types=["Person", "Organization", "Concept"],
    output_format="json"
)
```

## Core Module

- `ipfs_datasets_py.processors` — file conversion pipeline

## Dependencies

- `pdfminer.six` or `PyMuPDF` — PDF conversion
- `python-docx` — DOCX conversion
- `requests` — URL downloads
- `zipfile`, `tarfile` — archive extraction (stdlib)

## Status

| Tool | Status |
|------|--------|
| `convert_file` | ✅ Production ready |
| `batch_convert` | ✅ Production ready |
| `download_url` | ✅ Production ready |
| `extract_archive` | ✅ Production ready |
| `extract_knowledge_graph` | ✅ Production ready |
| `file_info` | ✅ Production ready |
| `generate_embeddings_from_file` | ✅ Production ready |
| `generate_summary` | ✅ Production ready (requires LLM API key) |
