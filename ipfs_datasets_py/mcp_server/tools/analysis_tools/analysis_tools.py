"""Analysis tools — thin MCP re-export shim.

All business logic lives in ipfs_datasets_py.analytics.analysis_engine.
"""
from __future__ import annotations

from ipfs_datasets_py.analytics.analysis_engine import (  # noqa: F401
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
    cluster_analysis,
    quality_assessment,
    dimensionality_reduction,
    analyze_data_distribution,
    perform_clustering_analysis,
    assess_embedding_quality,
    reduce_dimensionality,
)

__all__ = [
    "AnalysisEngine", "ClusteringAlgorithm", "QualityMetric", "DimensionalityMethod",
    "ClusterResult", "QualityAssessment", "DimensionalityResult",
    "get_analysis_engine", "detect_outliers", "analyze_diversity", "detect_drift",
    "analyze_similarity_patterns", "cluster_analysis", "quality_assessment",
    "dimensionality_reduction", "analyze_data_distribution",
    "perform_clustering_analysis", "assess_embedding_quality", "reduce_dimensionality",
]
