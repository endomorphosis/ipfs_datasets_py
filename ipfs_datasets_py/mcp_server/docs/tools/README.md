# Tool Category Reference

Navigation index for all **49+ tool categories** in the MCP server.  Each
category is a directory under `ipfs_datasets_py/mcp_server/tools/` that
contains one or more thin async wrapper functions exposing business logic
from canonical `ipfs_datasets_py.*` package modules.

> **Quick start:** Use `HierarchicalToolManager.dispatch(category, tool, params)` to call any tool.  
> See [THIN_TOOL_ARCHITECTURE.md](../../THIN_TOOL_ARCHITECTURE.md) for design principles.

---

## Core Categories

| Category | Directory | Key Tools | Business Logic |
|----------|-----------|-----------|----------------|
| `dataset_tools` | `dataset_tools/` | `load_dataset`, `save_dataset`, `convert_dataset` | `ipfs_datasets_py.DatasetManager` |
| `ipfs_tools` | `ipfs_tools/` | `pin_to_ipfs`, `get_from_ipfs` | `ipfs_datasets_py.core_operations.IPFSPinner` |
| `graph_tools` | `graph_tools/` | `graph_create`, `graph_add_entity`, `graph_query_cypher`, `graph_search_hybrid` | `ipfs_datasets_py.core_operations.KnowledgeGraphManager` |
| `search_tools` | `search_tools/` | `semantic_search`, `keyword_search` | `ipfs_datasets_py.search.SearchEngine` |
| `vector_tools` | `vector_tools/` | `vector_index`, `vector_search`, `vector_delete` | `ipfs_datasets_py.vector_stores` |
| `embedding_tools` | `embedding_tools/` | `create_embeddings`, `batch_embeddings` | `ipfs_datasets_py.embeddings.generation_engine` |
| `storage_tools` | `storage_tools/` | `store_data`, `retrieve_data`, `manage_collections`, `query_storage` | `storage_tools/storage_engine.py` |

## PDF & Document Processing

| Category | Directory | Key Tools |
|----------|-----------|-----------|
| `pdf_tools` | `pdf_tools/` | `pdf_to_text`, `pdf_analyze_relationships`, `pdf_cross_document_analysis`, `pdf_extract_entities`, `pdf_batch_process`, `pdf_optimize_for_llm` |
| `file_converter_tools` | `file_converter_tools/` | `convert_file_tool`, `batch_convert_tool`, `file_info_tool`, `extract_archive_tool`, `generate_summary_tool`, `download_url_tool` |
| `file_detection_tools` | `file_detection_tools/` | `detect_file_type`, `detect_encoding` |

## Multimedia & Media

| Category | Directory | Key Tools | Business Logic |
|----------|-----------|-----------|----------------|
| `media_tools` | `media_tools/` | `ffmpeg_edit`, `ffmpeg_info`, `ytdlp_download` | `ipfs_datasets_py.processors.multimedia.*` |
| `email_tools` | `email_tools/` | `email_export`, `email_analyze` | `ipfs_datasets_py.processors.multimedia.email_*` |
| `discord_tools` | `discord_tools/` | `discord_export`, `discord_analyze` | `ipfs_datasets_py.processors.discord.*` |

## Legal & Regulatory

| Category | Directory | Key Tools | Business Logic |
|----------|-----------|-----------|----------------|
| `legal_dataset_tools` | `legal_dataset_tools/` | `scrape_court_opinions`, `scrape_state_statutes`, `legal_graphrag`, `multilanguage_search`, `citation_extraction` | `ipfs_datasets_py.processors.legal_scrapers.*` |

## Development & DevOps

| Category | Directory | Key Tools | Business Logic |
|----------|-----------|-----------|----------------|
| `development_tools` | `development_tools/` | `lint_codebase`, `run_tests`, `test_generator`, `automated_pr_review`, `github_cli_*`, `vscode_cli_*` | `ipfs_datasets_py.processors.development.*` |
| `software_engineering_tools` | `software_engineering_tools/` | `dag_workflow`, `dependency_analysis`, `kubernetes_log`, `auto_healing` | `ipfs_datasets_py.processors.development.*` |
| `bespoke_tools` | `bespoke_tools/` | `execute_workflow` | `ipfs_datasets_py.processors.development.bespoke_workflow_engine` |

## Search & Web Archive

| Category | Directory | Key Tools | Business Logic |
|----------|-----------|-----------|----------------|
| `web_archive_tools` | `web_archive_tools/` | `search_wayback`, `search_google`, `search_brave`, `search_serpstack`, `search_openverse`, `search_huggingface`, `search_github` | `ipfs_datasets_py.web_archiving.*` |
| `web_scraping_tools` | `web_scraping_tools/` | `scrape_url`, `autoscraper`, `archive_is` | `ipfs_datasets_py.web_archiving.*` |

## Analytics & Monitoring

| Category | Directory | Key Tools | Business Logic |
|----------|-----------|-----------|----------------|
| `analysis_tools` | `analysis_tools/` | `cluster_analysis`, `quality_assessment`, `dimensionality_reduction` | `ipfs_datasets_py.analytics.analysis_engine` |
| `monitoring_tools` | `monitoring_tools/` | `health_check`, `get_performance_metrics`, `monitor_services` | `ipfs_datasets_py.monitoring_engine` |
| `alert_tools` | `alert_tools/` | `send_discord_alert`, `send_email_alert` | `alert_tools/discord_alert_tools.py` |
| `dashboard_tools` | `dashboard_tools/` | Dashboard management tools | `dashboard_tools/` |

## AI & ML

| Category | Directory | Key Tools |
|----------|-----------|-----------|
| `sparse_embedding_tools` | `sparse_embedding_tools/` | `sparse_embed_text`, `sparse_search` |
| `finance_data_tools` | `finance_data_tools/` | `embedding_correlation`, `market_analysis` |
| `medical_research_scrapers` | `medical_research_scrapers/` | `scrape_pubmed`, `scrape_clinical_trials` |

## Logic & Theorem Proving

| Category | Directory | Key Tools |
|----------|-----------|-----------|
| `logic_tools` | `logic_tools/` | `cec_prove`, `cec_parse`, `cec_analysis`, `tdfol_prove`, `logic_graphrag` |

## P2P & Distributed

| Category | Directory | Key Tools | Business Logic |
|----------|-----------|-----------|----------------|
| `p2p_tools` | `p2p_tools/` | `p2p_service_status`, `p2p_task_submit` | `ipfs_accelerate_py.p2p_tasks` |
| `p2p_workflow_tools` | `p2p_workflow_tools/` | `initialize_p2p_scheduler`, `submit_workflow`, `get_workflow_status` | `ipfs_datasets_py.p2p_networking` |
| `ipfs_cluster_tools` | `ipfs_cluster_tools/` | `cluster_status`, `cluster_pin`, `cluster_peers` | `ipfs_datasets_py.ipfs_cluster` |

## Security, Audit & Provenance

| Category | Directory | Key Tools |
|----------|-----------|-----------|
| `security_tools` | `security_tools/` | `scan_file`, `validate_input`, `generate_security_report` |
| `audit_tools` | `audit_tools/` | `record_audit_event`, `generate_audit_report` |
| `provenance_tools` | `provenance_tools/` | `record_provenance` |

## Session & Infrastructure

| Category | Directory | Key Tools |
|----------|-----------|-----------|
| `auth_tools` | `auth_tools/` | `authenticate`, `authorize`, `refresh_token` |
| `admin_tools` | `admin_tools/` | `server_health`, `tool_registry`, `config_update` |
| `session_tools` | `session_tools/` | `session_create`, `session_get`, `session_delete` |
| `background_task_tools` | `background_task_tools/` | `task_create`, `task_status`, `task_cancel` |
| `cache_tools` | `cache_tools/` | `get_cache_stats`, `manage_cache`, `monitor_cache` |
| `rate_limiting_tools` | `rate_limiting_tools/` | `check_rate_limit`, `configure_rate_limit` |

## Geospatial & Investigation

| Category | Directory | Key Tools |
|----------|-----------|-----------|
| `geospatial_tools` | `geospatial_tools/` | `geocode`, `reverse_geocode`, `distance_calculation` |
| `investigation_tools` | `investigation_tools/` | `data_ingestion`, `codebase_search`, `tdfol_performance` |
| `index_management_tools` | `index_management_tools/` | `index_create`, `index_delete`, `index_rebuild` |

## MCP++

| Category | Directory | Key Tools | Business Logic |
|----------|-----------|-----------|----------------|
| `mcplusplus` (taskqueue) | `mcplusplus_taskqueue_tools.py` | `task_submit`, `task_status`, `queue_stats`, `worker_register` | `mcplusplus/taskqueue_engine.py` |
| `mcplusplus` (peers) | `mcplusplus_peer_tools.py` | `peer_discover`, `peer_connect`, `peer_disconnect` | `mcplusplus/peer_engine.py` |
| `mcplusplus` (workflow) | `mcplusplus_workflow_tools.py` | `workflow_create`, `workflow_execute`, `workflow_status` | `mcplusplus/workflow_engine.py` |

---

## Tool Discovery (Programmatic)

```python
import anyio
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

async def main():
    manager = HierarchicalToolManager()
    # List all categories
    categories = await manager.list_categories(include_count=True)
    # List tools in a category
    tools = await manager.list_tools("graph_tools")
    # Get a tool's schema
    schema = await manager.get_tool_schema("graph_tools", "graph_create")
    # Dispatch a tool call
    result = await manager.dispatch("graph_tools", "graph_create", {})
    print(result)

anyio.run(main)
```

## Related Documentation

- [THIN_TOOL_ARCHITECTURE.md](../../THIN_TOOL_ARCHITECTURE.md) — Design principles
- [API Reference](../api/tool-reference.md) — Complete API documentation
- [Development Guide](../development/) — Creating new tools
- [Performance Tuning](../guides/performance-tuning.md) — Caching and optimisation
