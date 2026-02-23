"""
.. deprecated::

    This module has been relocated to
    ``ipfs_datasets_py.knowledge_graphs.lineage.cross_document``.
    Update your imports accordingly.
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.knowledge_graphs.cross_document_lineage is deprecated. "
    "Use ipfs_datasets_py.knowledge_graphs.lineage.cross_document instead.",
    DeprecationWarning,
    stacklevel=2,
)
from ipfs_datasets_py.knowledge_graphs.lineage.cross_document import *  # noqa: F401, F403
from ipfs_datasets_py.knowledge_graphs.lineage.cross_document import (  # noqa: F401
    LineageNode,
    LineageLink,
    LineageDomain,
    LineageBoundary,
    LineageTransformationDetail,
    LineageVersion,
    LineageSubgraph,
    LineageGraph,
    LineageTracker,
    SemanticAnalyzer,
    BoundaryDetector,
    ConfidenceScorer,
    EnhancedLineageTracker,
    LineageVisualizer,
    LineageMetrics,
    ImpactAnalyzer,
    DependencyAnalyzer,
    CrossDocumentLineageTracker,
    CrossDocumentLineageGraph,
)
