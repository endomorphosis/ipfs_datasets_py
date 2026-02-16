"""
Cross-Document Lineage Tracking Module with Enhanced Data Provenance.

⚠️ DEPRECATED: This module is deprecated. Please use the lineage/ package instead.

Migration Guide:
    OLD: from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import CrossDocumentLineageTracker
    NEW: from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker

    OLD: from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import LineageGraph
    NEW: from ipfs_datasets_py.knowledge_graphs.lineage import LineageGraph

See docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for complete migration instructions.

This file will be removed in version 2.0 (estimated Q2 2026).
"""

import warnings
import sys

# Issue deprecation warning when module is imported
warnings.warn(
    "cross_document_lineage module is deprecated. "
    "Please use 'from ipfs_datasets_py.knowledge_graphs.lineage import ...' instead. "
    "See docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for migration guide. "
    "This module will be removed in version 2.0.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export everything from the new lineage package for backward compatibility
from ipfs_datasets_py.knowledge_graphs.lineage import (
    # Types
    LineageNode,
    LineageLink,
    LineageDomain,
    LineageBoundary,
    LineageTransformationDetail,
    LineageVersion,
    LineageSubgraph,
    # Core classes
    LineageGraph,
    LineageTracker,
    # Enhanced classes
    SemanticAnalyzer,
    BoundaryDetector,
    ConfidenceScorer,
    EnhancedLineageTracker,
    # Visualization
    LineageVisualizer,
    # Metrics
    LineageMetrics,
    ImpactAnalyzer,
    DependencyAnalyzer,
)

# Deprecated aliases for backward compatibility
CrossDocumentLineageTracker = LineageTracker
CrossDocumentLineageGraph = LineageGraph

__all__ = [
    'LineageNode',
    'LineageLink',
    'LineageDomain',
    'LineageBoundary',
    'LineageTransformationDetail',
    'LineageVersion',
    'LineageSubgraph',
    'LineageGraph',
    'LineageTracker',
    'SemanticAnalyzer',
    'BoundaryDetector',
    'ConfidenceScorer',
    'EnhancedLineageTracker',
    'LineageVisualizer',
    'LineageMetrics',
    'ImpactAnalyzer',
    'DependencyAnalyzer',
    # Deprecated aliases
    'CrossDocumentLineageTracker',
    'CrossDocumentLineageGraph',
]
