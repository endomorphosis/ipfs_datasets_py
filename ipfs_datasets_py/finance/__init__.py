"""Finance package.

Core finance functionality should live under :mod:`ipfs_datasets_py.finance`.
MCP tools and CLIs should wrap these modules (not the other way around).
"""

from __future__ import annotations

from ipfs_datasets_py.finance.graphrag_news import (
    GraphRAGNewsAnalyzer,
    analyze_news_with_graphrag,
    create_financial_knowledge_graph,
    analyze_executive_performance,
    extract_executive_profiles_from_archives,
)


GRAPHRAG_AVAILABLE = True


__all__ = [
    "GraphRAGNewsAnalyzer",
    "analyze_news_with_graphrag",
    "create_financial_knowledge_graph",
    "analyze_executive_performance",
    "extract_executive_profiles_from_archives",
    "GRAPHRAG_AVAILABLE",
]
