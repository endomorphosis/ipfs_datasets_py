"""
.. deprecated::

    This module has been relocated to
    ``ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag``.
    Update your imports accordingly.
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.knowledge_graphs.finance_graphrag is deprecated. "
    "Use ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag instead.",
    DeprecationWarning,
    stacklevel=2,
)
from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import *  # noqa: F401, F403
from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import (  # noqa: F401
    ExecutiveProfile,
    CompanyPerformance,
    HypothesisTest,
    GraphRAGNewsAnalyzer,
    analyze_news_with_graphrag,
    create_financial_knowledge_graph,
    analyze_executive_performance,
    extract_executive_profiles_from_archives,
    GRAPHRAG_AVAILABLE,
)
