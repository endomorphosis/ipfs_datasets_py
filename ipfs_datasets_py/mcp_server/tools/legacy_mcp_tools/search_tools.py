# src/mcp_server/tools/search_tools.py
# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.search_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.search_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.search_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (  # noqa: F401, E402
    semantic_search,
    similarity_search,
    faceted_search,
    SemanticSearchTool,
    SimilaritySearchTool,
    FacetedSearchTool,
)

__all__ = [
    "semantic_search",
    "similarity_search",
    "faceted_search",
    "SemanticSearchTool",
    "SimilaritySearchTool",
    "FacetedSearchTool",
]
