"""
Analytics components for cross-website analysis and global trend detection.

This package provides advanced analytics capabilities for understanding patterns,
correlations, and trends across multiple websites processed by GraphRAG.

It also includes core analysis engine for clustering, quality assessment, and
dimensionality reduction.
"""

# Always import core analysis engine (no heavy dependencies)
from .analysis_engine import (
    AnalysisEngine,
    ClusteringAlgorithm,
    QualityMetric,
    DimensionalityMethod,
    ClusterResult,
    QualityAssessment,
    DimensionalityResult,
    get_analysis_engine,
    detect_outliers,
    analyze_diversity,
    detect_drift,
    analyze_similarity_patterns,
)

# Try to import cross-website analyzer (has optional dependencies)
try:
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
    _HAVE_CROSS_WEBSITE = True
except ImportError as e:
    _HAVE_CROSS_WEBSITE = False
    # Create stub classes/functions
    CrossWebsiteAnalyzer = None
    WebsiteCorrelation = None
    GlobalTrend = None
    CrossSiteAnalysisReport = None
    GlobalKnowledgeGraph = None
    ContentSimilarityAnalyzer = None
    TrendDetectionEngine = None
    GlobalKnowledgeGraphIntegrator = None
    analyze_multiple_websites = None
    create_global_knowledge_graph = None

__all__ = [
    # Core analysis engine (always available)
    'AnalysisEngine',
    'ClusteringAlgorithm',
    'QualityMetric',
    'DimensionalityMethod',
    'ClusterResult',
    'QualityAssessment',
    'DimensionalityResult',
    'get_analysis_engine',
    
    # Cross-website analysis (optional)
    'CrossWebsiteAnalyzer',
    'WebsiteCorrelation',
    'GlobalTrend', 
    'CrossSiteAnalysisReport',
    'GlobalKnowledgeGraph',
    'ContentSimilarityAnalyzer',
    'TrendDetectionEngine',
    'GlobalKnowledgeGraphIntegrator',
    'analyze_multiple_websites',
    'create_global_knowledge_graph',
]