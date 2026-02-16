"""
Enhanced Cross-Document Lineage Tracking

⚠️ DEPRECATED: This module is deprecated. Please use the lineage/ package instead.

Migration Guide:
    OLD: from ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced import EnhancedLineageTracker
    NEW: from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker

    OLD: from ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced import SemanticAnalyzer
    NEW: from ipfs_datasets_py.knowledge_graphs.lineage import SemanticAnalyzer

See docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for complete migration instructions.

This file will be removed in version 2.0 (estimated Q2 2026).
"""

import warnings

# Issue deprecation warning when module is imported
warnings.warn(
    "cross_document_lineage_enhanced module is deprecated. "
    "Please use 'from ipfs_datasets_py.knowledge_graphs.lineage import ...' instead. "
    "See docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for migration guide. "
    "This module will be removed in version 2.0.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export everything from the new lineage package for backward compatibility
from ipfs_datasets_py.knowledge_graphs.lineage import (
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

# Deprecated aliases
CrossDocumentLineageEnhancer = EnhancedLineageTracker

__all__ = [
    'SemanticAnalyzer',
    'BoundaryDetector',
    'ConfidenceScorer',
    'EnhancedLineageTracker',
    'LineageVisualizer',
    'LineageMetrics',
    'ImpactAnalyzer',
    'DependencyAnalyzer',
    # Deprecated aliases
    'CrossDocumentLineageEnhancer',
]
