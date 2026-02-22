# Legacy MCP Tools — Migration Guide

The `legacy_mcp_tools/` directory contains the original monolithic MCP tool files from before the
category-based directory structure was introduced. Most of these files have been superseded by
dedicated category directories with individual tool files that follow the
[Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md).

**This directory is preserved for backward compatibility.** New development should target the
appropriate category directory instead.

---

## Migration Map

The table below maps each legacy file to its current canonical location. Use the new location
for all new development and when updating existing code.

| Legacy File | Superseded By | Status |
|-------------|---------------|--------|
| `admin_tools.py` | [`../admin_tools/`](../admin_tools/) | ⚠️ Superseded |
| `analysis_tools.py` | [`../analysis_tools/`](../analysis_tools/) | ⚠️ Superseded |
| `authentication_tools.py` | [`../auth_tools/`](../auth_tools/) | ⚠️ Superseded |
| `automated_pr_review_tools.py` | [`../development_tools/automated_pr_review_tools.py`](../development_tools/automated_pr_review_tools.py) | ⚠️ Superseded |
| `background_task_tools.py` | [`../background_task_tools/`](../background_task_tools/) | ⚠️ Superseded |
| `cache_tools.py` | [`../cache_tools/`](../cache_tools/) | ⚠️ Superseded |
| `claude_cli_tools.py` | [`../development_tools/claude_cli_tools.py`](../development_tools/claude_cli_tools.py) | ⚠️ Superseded (shim to server tools) |
| `copilot_cli_tools.py` | [`../development_tools/copilot_cli_tools.py`](../development_tools/copilot_cli_tools.py) | ⚠️ Superseded |
| `create_embeddings_tool.py` | [`../embedding_tools/embedding_generation.py`](../embedding_tools/embedding_generation.py) | ⚠️ Superseded |
| `data_processing_tools.py` | [`../data_processing_tools/`](../data_processing_tools/) | ⚠️ Superseded |
| `embedding_tools.py` | [`../embedding_tools/`](../embedding_tools/) | ⚠️ Superseded |
| `gemini_cli_tools.py` | [`../development_tools/gemini_cli_tools.py`](../development_tools/gemini_cli_tools.py) | ⚠️ Superseded (shim to server tools) |
| `geospatial_tools.py` | [`../geospatial_tools/`](../geospatial_tools/) | ⚠️ Superseded |
| `github_cli_tools.py` | [`../development_tools/github_cli_tools.py`](../development_tools/github_cli_tools.py) | ⚠️ Superseded (shim to server tools) |
| `index_management_tools.py` | [`../index_management_tools/`](../index_management_tools/) | ⚠️ Superseded |
| `ipfs_cluster_tools.py` | [`../ipfs_cluster_tools/`](../ipfs_cluster_tools/) | ⚠️ Superseded |
| `legal_dataset_mcp_tools.py` | [`../legal_dataset_tools/`](../legal_dataset_tools/) | ⚠️ Superseded |
| `monitoring_tools.py` | [`../monitoring_tools/`](../monitoring_tools/) | ⚠️ Superseded |
| `municipal_scraper_fallbacks.py` | [`../legal_dataset_tools/municipal_scraper_fallbacks.py`](../legal_dataset_tools/municipal_scraper_fallbacks.py) | ⚠️ Superseded |
| `patent_dataset_mcp_tools.py` | [`../legal_dataset_tools/patent_dataset_mcp_tools.py`](../legal_dataset_tools/patent_dataset_mcp_tools.py) | ⚠️ Superseded |
| `patent_scraper.py` | [`../legal_dataset_tools/`](../legal_dataset_tools/) | ⚠️ Superseded |
| `rate_limiting_tools.py` | [`../rate_limiting_tools/`](../rate_limiting_tools/) | ⚠️ Superseded |
| `search_tools.py` | [`../search_tools/`](../search_tools/) | ⚠️ Superseded |
| `session_management_tools.py` | [`../session_tools/`](../session_tools/) | ⚠️ Superseded |
| `shard_embeddings_tool.py` | [`../embedding_tools/shard_embeddings_tool.py`](../embedding_tools/shard_embeddings_tool.py) | ⚠️ Superseded |
| `sparse_embedding_tools.py` | [`../sparse_embedding_tools/`](../sparse_embedding_tools/) | ⚠️ Superseded |
| `storage_tools.py` | [`../storage_tools/`](../storage_tools/) | ⚠️ Superseded |
| `temporal_deontic_logic_tools.py` | [`../logic_tools/temporal_deontic_logic_tools.py`](../logic_tools/temporal_deontic_logic_tools.py) | ⚠️ Superseded |
| `tool_wrapper.py` | [`../tool_wrapper.py`](../tool_wrapper.py) | ⚠️ Superseded |
| `vector_store_tools.py` | [`../vector_store_tools/`](../vector_store_tools/) | ⚠️ Superseded |
| `vscode_cli_tools.py` | [`../development_tools/vscode_cli_tools.py`](../development_tools/vscode_cli_tools.py) | ⚠️ Superseded |
| `workflow_tools.py` | [`../workflow_tools/`](../workflow_tools/) | ⚠️ Superseded |

---

## Import Migration Examples

### Before (legacy)

```python
# Old import from legacy monolithic module
from ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.embedding_tools import (
    generate_embeddings, semantic_search
)

from ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.vector_store_tools import (
    create_vector_index, search_vector_store
)
```

### After (current)

```python
# New imports from category directories
from ipfs_datasets_py.mcp_server.tools.embedding_tools import (
    generate_embeddings, semantic_search
)

from ipfs_datasets_py.mcp_server.tools.vector_store_tools import (
    create_vector_index, search_vector_store
)
```

---

## Files with No Direct Replacement

The following legacy files contain functionality that has not yet been fully migrated to a
dedicated category directory. They remain the canonical source until migration is complete:

| File | Notes |
|------|-------|
| `automated_pr_review_tools.py` | Present in both legacy and `development_tools/` — use the development_tools version |
| `municipal_scraper_fallbacks.py` | Fallback logic for municipal scrapers — also in `legal_dataset_tools/` |

---

## Backward Compatibility

All legacy files are preserved and continue to work. No code will be broken by their presence.
However:

1. **New tools** must be added to the appropriate category directory, not to `legacy_mcp_tools/`
2. **Bug fixes** should be applied to the canonical location (new category) first, then cherry-picked
   to the legacy file if needed for backward compatibility
3. **Tests** for legacy tools should be migrated to use the new category import path

---

## Removal Timeline

The `legacy_mcp_tools/` directory will be kept indefinitely for backward compatibility.
Individual files may be deprecated with `DeprecationWarning` on import once the canonical
category version is confirmed as stable and complete.

To add a deprecation warning to a legacy file:

```python
# At the top of the legacy file, after imports:
import warnings
warnings.warn(
    "legacy_mcp_tools.embedding_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.embedding_tools instead.",
    DeprecationWarning,
    stacklevel=2
)
```

---

**Last Updated:** 2026-02-20  
**Related:** [TOOLS_IMPROVEMENT_PLAN_2026.md](../TOOLS_IMPROVEMENT_PLAN_2026.md) · [../README.md](../README.md)
