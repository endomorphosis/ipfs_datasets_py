"""P2P networking and libp2p integration for IPFS Datasets Python.

This package includes peer registry, connectivity helpers, workflow scheduling,
and optional libp2p integration.

Note: This package previously performed eager star-imports of many submodules at
import time. That was brittle (optional deps) and unnecessarily heavy. We keep
this package importable by lazily importing submodules.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "p2p_connectivity",
    "p2p_peer_registry",
    "p2p_workflow_scheduler",
    "libp2p_kit",
    "libp2p_kit_full",
    "libp2p_kit_stub",
    "cli",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(name)

# --- Engine modules (moved from mcp_server/tools/mcplusplus) ---
try:
    from .peer_engine import PeerEngine
    from .taskqueue_engine import TaskQueueEngine
    from .workflow_engine import WorkflowEngine
except ImportError:
    pass
