"""Legacy shim for enhanced GraphRAG integration.

Canonical module:
- `ipfs_datasets_py.graphrag.integrations.enhanced_graphrag_integration`
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.logic.integrations.enhanced_graphrag_integration is deprecated; "
    "use ipfs_datasets_py.graphrag.integrations.enhanced_graphrag_integration",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.graphrag.integrations.enhanced_graphrag_integration import *  # noqa: F403
