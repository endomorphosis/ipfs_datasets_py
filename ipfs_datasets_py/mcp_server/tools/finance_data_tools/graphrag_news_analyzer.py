"""MCP wrapper for finance GraphRAG news analysis.

This module is part of the MCP tool surface area.
The implementation lives in :mod:`ipfs_datasets_py.finance.graphrag_news`.
"""

from __future__ import annotations

from ipfs_datasets_py.finance.graphrag_news import (  # noqa: F401
    ExecutiveProfile,
    CompanyPerformance,
    HypothesisTest,
    GraphRAGNewsAnalyzer,
    analyze_news_with_graphrag,
    create_financial_knowledge_graph,
    analyze_executive_performance,
    extract_executive_profiles_from_archives,
)

__all__ = [
    "ExecutiveProfile",
    "CompanyPerformance",
    "HypothesisTest",
    "GraphRAGNewsAnalyzer",
    "analyze_news_with_graphrag",
    "create_financial_knowledge_graph",
    "analyze_executive_performance",
    "extract_executive_profiles_from_archives",
]
