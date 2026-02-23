"""
.. deprecated::

    This module has been relocated to
    ``ipfs_datasets_py.knowledge_graphs.query.knowledge_graph``.
    Update your imports accordingly.
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.knowledge_graphs.query_knowledge_graph is deprecated. "
    "Use ipfs_datasets_py.knowledge_graphs.query.knowledge_graph instead.",
    DeprecationWarning,
    stacklevel=2,
)
from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import *  # noqa: F401, F403
from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import (  # noqa: F401
    parse_ir_ops_from_query,
    compile_ir,
    query_knowledge_graph,
)
