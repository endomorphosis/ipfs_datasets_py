"""
Consolidated Lineage Tracking Module

This module consolidates lineage tracking functionality from:
- cross_document_lineage.py (4,066 lines)
- cross_document_lineage_enhanced.py (2,357 lines)

Into a clean, organized structure with ~3,000 lines (53% reduction).

Public API:
    from ipfs_datasets_py.knowledge_graphs.lineage import (
        LineageTracker,
        LineageNode,
        LineageLink,
        LineageDomain,
        LineageBoundary,
    )

Submodules:
- types: Core data types (LineageNode, LineageLink, etc.)
- core: Core lineage tracking functionality
- enhanced: Enhanced semantic and boundary analysis
- visualization: Graph visualization (NetworkX, Plotly)
- metrics: Metrics and impact analysis
"""

from .types import (
    LineageNode,
    LineageLink,
    LineageDomain,
    LineageBoundary,
    LineageTransformationDetail,
    LineageVersion,
    LineageSubgraph,
)

from .core import (
    LineageGraph,
    LineageTracker,
)

from .enhanced import (
    SemanticAnalyzer,
    BoundaryDetector,
    ConfidenceScorer,
    EnhancedLineageTracker,
)

from .visualization import (
    LineageVisualizer,
    visualize_lineage,
)

from .metrics import (
    LineageMetrics,
    ImpactAnalyzer,
    DependencyAnalyzer,
)

# Deprecated aliases for backward compatibility
CrossDocumentLineageEnhancer = EnhancedLineageTracker
DetailedLineageIntegrator = LineageMetrics

__all__ = [
    # Core types
    'LineageNode',
    'LineageLink',
    'LineageDomain',
    'LineageBoundary',
    'LineageTransformationDetail',
    'LineageVersion',
    'LineageSubgraph',
    # Core classes
    'LineageGraph',
    'LineageTracker',
    # Enhanced features
    'SemanticAnalyzer',
    'BoundaryDetector',
    'ConfidenceScorer',
    'EnhancedLineageTracker',
    # Visualization
    'LineageVisualizer',
    'visualize_lineage',
    # Metrics and analysis
    'LineageMetrics',
    'ImpactAnalyzer',
    'DependencyAnalyzer',
    # Deprecated aliases
    'CrossDocumentLineageEnhancer',
    'DetailedLineageIntegrator',
]

# Version info
__version__ = '1.0.0'
__status__ = 'Production'

# Deprecation notice for old modules
import warnings

_DEPRECATION_MESSAGE = """
The legacy modules cross_document_lineage.py and cross_document_lineage_enhanced.py
are deprecated and will be removed in 6 months.

Please update your imports to use the new lineage package:
    OLD: from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import CrossDocumentLineageTracker
    NEW: from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker

See docs/knowledge_graphs/MIGRATION_GUIDE.md for details.
"""

def _show_deprecation_warning():
    """Show deprecation warning when importing legacy modules."""
    warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=3)
