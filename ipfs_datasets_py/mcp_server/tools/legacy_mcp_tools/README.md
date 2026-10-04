# Legacy MCP Tools

This directory contains **32 pre-refactoring tool files** that were part of the original monolithic
tool implementation before the thin-wrapper architecture was introduced (Phase 5).

> ⚠️ **These tools are being actively migrated.** New development should go in the appropriate
> category-specific directories (e.g. `dataset_tools/`, `search_tools/`, etc.).
> See [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) for migration instructions.

## Contents

| File | Description | Migration Target |
|------|-------------|-----------------|
| `admin_tools.py` | Server admin operations | → `admin_tools/` |
| `analysis_tools.py` | Data analysis utilities | → `analysis_tools/` |
| `authentication_tools.py` | Auth helpers | → `auth_tools/` |
| `automated_pr_review_tools.py` | GitHub PR review automation | → `software_engineering_tools/` |
| `background_task_tools.py` | Async job management | → `background_task_tools/` |
| `cache_tools.py` | Caching operations | → `cache_tools/` |
| `claude_cli_tools.py` | Claude CLI integration | → `development_tools/` |
| `copilot_cli_tools.py` | GitHub Copilot CLI | → `development_tools/` |
| `create_embeddings_tool.py` | Embedding creation | → `embedding_tools/` |
| `data_processing_tools.py` | Data transformation | → `data_processing_tools/` |
| `embedding_tools.py` | Embedding utilities | → `embedding_tools/` |
| `gemini_cli_tools.py` | Gemini CLI integration | → `development_tools/` |
| `geospatial_tools.py` | Geographic data tools | → `geospatial_tools/` |
| `github_cli_tools.py` | GitHub CLI operations | → `development_tools/` |
| `index_management_tools.py` | Search index management | → `index_management_tools/` |
| `ipfs_cluster_tools.py` | IPFS cluster operations | → `ipfs_cluster_tools/` |
| `legal_dataset_mcp_tools.py` | Legal dataset scrapers | → `legal_dataset_tools/` |
| `monitoring_tools.py` | Metrics and health checks | → `monitoring_tools/` |
| `municipal_scraper_fallbacks.py` | Municipal scraper fallbacks | → `legal_dataset_tools/` |
| `patent_dataset_mcp_tools.py` | Patent dataset tools | → `legal_dataset_tools/` |
| `patent_scraper.py` | Patent scraping | → `legal_dataset_tools/` |
| `rate_limiting_tools.py` | API rate limiting | → `rate_limiting_tools/` |
| `search_tools.py` | Search operations | → `search_tools/` |
| `session_management_tools.py` | Session state | → `session_tools/` |
| `shard_embeddings_tool.py` | Embedding sharding | → `embedding_tools/` |
| `sparse_embedding_tools.py` | BM25/sparse embeddings | → `sparse_embedding_tools/` |
| `storage_tools.py` | Storage operations | → `storage_tools/` |
| `temporal_deontic_logic_tools.py` | Legal reasoning | → `logic_tools/` |
| `tool_wrapper.py` | Legacy wrapper utilities | Superseded by `tool_wrapper.py` at tools root |
| `vector_store_tools.py` | Vector store operations | → `vector_store_tools/` |
| `vscode_cli_tools.py` | VSCode CLI integration | → `development_tools/` |
| `workflow_tools.py` | Workflow orchestration | → `workflow_tools/` |

## Migration Status

Most business logic from these files has been extracted and moved to the appropriate category
directories as thin wrappers. These legacy files are kept for backwards compatibility until
all callers have been updated.

See [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) for the detailed migration checklist.
