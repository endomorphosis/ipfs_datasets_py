# Lizardperson Argparse Programs

This directory contains the **Municipal Bluebook Citation Validator** — a legacy CLI program
originally written as an argparse application. It has been superseded by an MCP wrapper tool.

> 📌 **MCP wrapper:** `legal_dataset_tools/bluebook_citation_validator_tool.py`  
> Use the MCP wrapper for AI assistant integration.

## Contents

### `municipal_bluebook_citation_validator/`

A standalone Python CLI application that validates municipal code citations against the
Bluebook legal citation standard. Key files:

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point (argparse) |
| `citation_validator/` | Core citation validation logic |
| `stratified_sampler/` | Sampling utilities for validation testing |
| `results_analyzer/` | Analysis of validation results |
| `generate_reports/` | Report generation utilities |
| `configs.py` | Configuration management |
| `types_.py` | Type definitions |
| `dependencies.py` | Dependency declarations |

### Other Subdirectories

| Directory | Purpose |
|-----------|---------|
| `cli/` | CLI interface utilities |
| `functions/` | Shared function helpers |
| `llm_context_tools/` | LLM context management tools |
| `meta_tools/` | Meta-programming utilities |
| `prototyping_tools/` | Rapid prototyping helpers |
| `test_tools/` | Test utility tools |

## Status

This directory is **legacy / reference only**. The CLI functionality is exposed as an MCP
tool through:

```
ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/bluebook_citation_validator_tool.py
```

No new development should be added here.
