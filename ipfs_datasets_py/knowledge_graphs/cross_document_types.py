"""
.. deprecated::

    This module has been relocated to
    ``ipfs_datasets_py.knowledge_graphs.reasoning.types``.
    Update your imports accordingly.
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.knowledge_graphs.cross_document_types is deprecated. "
    "Use ipfs_datasets_py.knowledge_graphs.reasoning.types instead.",
    DeprecationWarning,
    stacklevel=2,
)
from ipfs_datasets_py.knowledge_graphs.reasoning.types import *  # noqa: F401, F403
from ipfs_datasets_py.knowledge_graphs.reasoning.types import (  # noqa: F401
    InformationRelationType,
    DocumentNode,
    EntityMediatedConnection,
    CrossDocReasoning,
)
