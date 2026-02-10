"""Legacy shim for Phase 7 GraphRAG integration.

Canonical module:
- `ipfs_datasets_py.graphrag.integrations.phase7_complete_integration`
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.logic.integrations.phase7_complete_integration is deprecated; "
    "use ipfs_datasets_py.graphrag.integrations.phase7_complete_integration",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.graphrag.integrations.phase7_complete_integration import *  # noqa: F403
