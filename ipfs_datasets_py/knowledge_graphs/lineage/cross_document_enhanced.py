"""
Enhanced cross-document lineage tracking — canonical location within the lineage subpackage.

This module re-exports the enhanced lineage public API for users who prefer a
more explicit import path.
"""

from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import (
    SemanticAnalyzer,
    BoundaryDetector,
    ConfidenceScorer,
    EnhancedLineageTracker,
)
from ipfs_datasets_py.knowledge_graphs.lineage.visualization import (
    LineageVisualizer,
    visualize_lineage,
)
from ipfs_datasets_py.knowledge_graphs.lineage.metrics import (
    LineageMetrics,
    ImpactAnalyzer,
    DependencyAnalyzer,
)

# Backward-compatible aliases
CrossDocumentLineageEnhancer = EnhancedLineageTracker
DetailedLineageIntegrator = LineageMetrics

__all__ = [
    "SemanticAnalyzer",
    "BoundaryDetector",
    "ConfidenceScorer",
    "EnhancedLineageTracker",
    "LineageVisualizer",
    "visualize_lineage",
    "LineageMetrics",
    "ImpactAnalyzer",
    "DependencyAnalyzer",
    "CrossDocumentLineageEnhancer",
    "DetailedLineageIntegrator",
]
