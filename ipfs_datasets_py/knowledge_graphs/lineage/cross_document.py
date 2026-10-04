"""
Cross-document lineage tracking — canonical location within the lineage subpackage.

This module re-exports the public API from the lineage package for users who
prefer a more explicit import path for cross-document lineage functionality.
"""

from ipfs_datasets_py.knowledge_graphs.lineage.types import (
    LineageNode,
    LineageLink,
    LineageDomain,
    LineageBoundary,
    LineageTransformationDetail,
    LineageVersion,
    LineageSubgraph,
)
from ipfs_datasets_py.knowledge_graphs.lineage.core import (
    LineageGraph,
    LineageTracker,
)
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
CrossDocumentLineageTracker = LineageTracker
CrossDocumentLineageGraph = LineageGraph

__all__ = [
    "LineageNode",
    "LineageLink",
    "LineageDomain",
    "LineageBoundary",
    "LineageTransformationDetail",
    "LineageVersion",
    "LineageSubgraph",
    "LineageGraph",
    "LineageTracker",
    "SemanticAnalyzer",
    "BoundaryDetector",
    "ConfidenceScorer",
    "EnhancedLineageTracker",
    "LineageVisualizer",
    "visualize_lineage",
    "LineageMetrics",
    "ImpactAnalyzer",
    "DependencyAnalyzer",
    "CrossDocumentLineageTracker",
    "CrossDocumentLineageGraph",
]
