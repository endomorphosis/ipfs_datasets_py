"""
.. deprecated::

    This module has been relocated to
    ``ipfs_datasets_py.knowledge_graphs.lineage.cross_document_enhanced``.
    Update your imports accordingly.
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced is deprecated. "
    "Use ipfs_datasets_py.knowledge_graphs.lineage.cross_document_enhanced instead.",
    DeprecationWarning,
    stacklevel=2,
)
from ipfs_datasets_py.knowledge_graphs.lineage.cross_document_enhanced import *  # noqa: F401, F403
from ipfs_datasets_py.knowledge_graphs.lineage.cross_document_enhanced import (  # noqa: F401
    SemanticAnalyzer,
    BoundaryDetector,
    ConfidenceScorer,
    EnhancedLineageTracker,
    LineageVisualizer,
    LineageMetrics,
    ImpactAnalyzer,
    DependencyAnalyzer,
    CrossDocumentLineageEnhancer,
    DetailedLineageIntegrator,
)
