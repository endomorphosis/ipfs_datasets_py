"""
Analytics components for cross-website analysis and global trend detection.

This package provides advanced analytics capabilities for understanding patterns,
correlations, and trends across multiple websites processed by GraphRAG.
"""

from .cross_website_analyzer import (
    CrossWebsiteAnalyzer,
    WebsiteCorrelation,
    GlobalTrend,
    CrossSiteAnalysisReport,
    GlobalKnowledgeGraph,
    ContentSimilarityAnalyzer,
    TrendDetectionEngine,
    GlobalKnowledgeGraphIntegrator,
    analyze_multiple_websites,
    create_global_knowledge_graph
)

__all__ = [
    'CrossWebsiteAnalyzer',
    'WebsiteCorrelation',
    'GlobalTrend', 
    'CrossSiteAnalysisReport',
    'GlobalKnowledgeGraph',
    'ContentSimilarityAnalyzer',
    'TrendDetectionEngine',
    'GlobalKnowledgeGraphIntegrator',
    'analyze_multiple_websites',
    'create_global_knowledge_graph'
]