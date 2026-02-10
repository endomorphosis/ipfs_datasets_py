"""Legacy shim for UnixFS integration.

Canonical module (current step):
- `ipfs_datasets_py.graphrag.integrations.unixfs_integration`

Note: a later consolidation step may move UnixFS primitives closer to IPLD.
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.logic.integrations.unixfs_integration is deprecated; "
    "use ipfs_datasets_py.graphrag.integrations.unixfs_integration",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.graphrag.integrations.unixfs_integration import *  # noqa: F403
