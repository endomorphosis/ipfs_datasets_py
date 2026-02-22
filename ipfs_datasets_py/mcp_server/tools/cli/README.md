# CLI

MCP-facing command-line execution utilities.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `execute_command.py` | `execute_command()` | Execute a shell command and return stdout/stderr/exit code |
| `medical_research_cli.py` | `scrape_pubmed()`, `run_clinical_trials()`, `discover_biomolecules()` | CLI entry points for medical research scrapers (delegates to `medical_research_scrapers/`) |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.cli import execute_command

result = await execute_command(
    command=["ffmpeg", "-version"],
    timeout=10,
    capture_stderr=True
)
# Returns: {"exit_code": 0, "stdout": "ffmpeg version ...", "stderr": ""}
```

> **Note:** For medical research operations, prefer the dedicated
> [`medical_research_scrapers/`](../medical_research_scrapers/) category which provides
> richer structured responses.

## Status

| Tool | Status |
|------|--------|
| `execute_command` | ✅ Production ready |
| `medical_research_cli` | ✅ Production ready (delegates to medical_research_scrapers) |
