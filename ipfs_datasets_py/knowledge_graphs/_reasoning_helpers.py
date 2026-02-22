"""
.. deprecated::

    This module has been relocated to
    ``ipfs_datasets_py.knowledge_graphs.reasoning.helpers``.
    Update your imports accordingly.
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.knowledge_graphs._reasoning_helpers is deprecated. "
    "Use ipfs_datasets_py.knowledge_graphs.reasoning.helpers instead.",
    DeprecationWarning,
    stacklevel=2,
)
from ipfs_datasets_py.knowledge_graphs.reasoning.helpers import *  # noqa: F401, F403
from ipfs_datasets_py.knowledge_graphs.reasoning.helpers import ReasoningHelpersMixin  # noqa: F401
