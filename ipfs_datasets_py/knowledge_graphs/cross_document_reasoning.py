"""
.. deprecated::

    This module has been relocated to
    ``ipfs_datasets_py.knowledge_graphs.reasoning.cross_document``.
    Update your imports accordingly.
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.knowledge_graphs.cross_document_reasoning is deprecated. "
    "Use ipfs_datasets_py.knowledge_graphs.reasoning.cross_document instead.",
    DeprecationWarning,
    stacklevel=2,
)
from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import *  # noqa: F401, F403
from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import CrossDocumentReasoner  # noqa: F401
# Re-export module-level attributes that _reasoning_helpers references at runtime
from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import (  # noqa: F401
    openai,
    anthropic,
    LLMRouter,
)
