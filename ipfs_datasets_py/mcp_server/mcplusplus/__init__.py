"""MCP++ Integration Layer for IPFS Datasets MCP Server.

This module provides graceful imports and adapters for the MCP++ module
from ipfs_accelerate_py. It enables advanced P2P capabilities including:
- Trio-native runtime (no asyncio-to-Trio bridges)
- P2P workflow scheduler
- Advanced task queue
- Peer registry and discovery
- Bootstrap helpers

All imports use graceful fallback, so the MCP server continues to function
even if ipfs_accelerate_py or its mcplusplus_module is unavailable.

Module: ipfs_datasets_py.mcp_server.mcplusplus
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Global flags for feature availability
HAVE_MCPLUSPLUS = False
HAVE_WORKFLOW_SCHEDULER = False
HAVE_TASK_QUEUE = False
HAVE_PEER_REGISTRY = False
HAVE_BOOTSTRAP = False
HAVE_TRIO_SERVER = False


def _ensure_ipfs_accelerate_on_path() -> None:
    """Make ipfs_accelerate_py importable if it's a submodule.

    In this workspace, ipfs_accelerate_py may be checked out as a submodule at:
        ipfs_datasets_py/ipfs_accelerate_py/
    which is not on sys.path by default.
    """
    try:
        # This file lives at: <root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/mcplusplus/
        # The submodule root is: <root>/ipfs_accelerate_py
        repo_root = Path(__file__).resolve().parents[4]
        candidate = repo_root / "ipfs_accelerate_py"

        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            logger.debug(f"Added ipfs_accelerate_py to sys.path: {candidate}")
    except Exception as e:
        logger.debug(f"Could not add ipfs_accelerate_py to sys.path: {e}")


# Ensure ipfs_accelerate_py is on path before importing
_ensure_ipfs_accelerate_on_path()


# Try to import MCP++ components with graceful fallback
try:
    from ipfs_accelerate_py.mcplusplus_module import __version__ as mcplusplus_version

    HAVE_MCPLUSPLUS = True
    logger.info(f"MCP++ module available (version: {mcplusplus_version})")
except ImportError as e:
    logger.info(f"MCP++ module not available: {e}")
    mcplusplus_version = None


# Import individual components
try:
    from ipfs_accelerate_py.mcplusplus_module.p2p.workflow import (
        P2PWorkflowScheduler,
        get_scheduler,
        reset_scheduler,
        HAVE_P2P_SCHEDULER,
    )

    if HAVE_P2P_SCHEDULER:
        HAVE_WORKFLOW_SCHEDULER = True
        logger.debug("P2P workflow scheduler available")
except ImportError as e:
    logger.debug(f"P2P workflow scheduler not available: {e}")
    P2PWorkflowScheduler = None  # type: ignore
    get_scheduler = None  # type: ignore
    reset_scheduler = None  # type: ignore
    HAVE_P2P_SCHEDULER = False


try:
    from ipfs_accelerate_py.mcplusplus_module.p2p.peer_registry import (
        PeerRegistry,
    )

    HAVE_PEER_REGISTRY = True
    logger.debug("Peer registry available")
except ImportError as e:
    logger.debug(f"Peer registry not available: {e}")
    PeerRegistry = None  # type: ignore


try:
    from ipfs_accelerate_py.mcplusplus_module.p2p.bootstrap import (
        bootstrap_network,
    )

    HAVE_BOOTSTRAP = True
    logger.debug("Bootstrap helpers available")
except ImportError as e:
    logger.debug(f"Bootstrap helpers not available: {e}")
    bootstrap_network = None  # type: ignore


try:
    from ipfs_accelerate_py.mcplusplus_module.trio.server import (
        TrioMCPServer,
        ServerConfig,
    )

    HAVE_TRIO_SERVER = True
    logger.debug("Trio MCP server available")
except ImportError as e:
    logger.debug(f"Trio MCP server not available: {e}")
    TrioMCPServer = None  # type: ignore
    ServerConfig = None  # type: ignore


# Task queue is always available (fallback to basic implementation)
HAVE_TASK_QUEUE = HAVE_MCPLUSPLUS


__all__ = [
    # Availability flags
    "HAVE_MCPLUSPLUS",
    "HAVE_WORKFLOW_SCHEDULER",
    "HAVE_TASK_QUEUE",
    "HAVE_PEER_REGISTRY",
    "HAVE_BOOTSTRAP",
    "HAVE_TRIO_SERVER",
    # Version
    "mcplusplus_version",
    # Components (may be None if not available)
    "P2PWorkflowScheduler",
    "get_scheduler",
    "reset_scheduler",
    "PeerRegistry",
    "bootstrap_network",
    "TrioMCPServer",
    "ServerConfig",
]


def get_capabilities() -> dict[str, Any]:
    """Get a dictionary of available MCP++ capabilities.

    Returns:
        Dictionary with capability flags and version information
    """
    return {
        "mcplusplus_available": HAVE_MCPLUSPLUS,
        "mcplusplus_version": mcplusplus_version,
        "capabilities": {
            "workflow_scheduler": HAVE_WORKFLOW_SCHEDULER,
            "task_queue": HAVE_TASK_QUEUE,
            "peer_registry": HAVE_PEER_REGISTRY,
            "bootstrap": HAVE_BOOTSTRAP,
            "trio_server": HAVE_TRIO_SERVER,
        },
    }


def check_requirements() -> tuple[bool, list[str]]:
    """Check if all required dependencies are available.

    Returns:
        Tuple of (all_available, missing_features)
    """
    missing = []

    if not HAVE_MCPLUSPLUS:
        missing.append("mcplusplus_module (ipfs_accelerate_py not installed)")
    if not HAVE_WORKFLOW_SCHEDULER:
        missing.append("workflow_scheduler")
    if not HAVE_TASK_QUEUE:
        missing.append("task_queue")
    if not HAVE_PEER_REGISTRY:
        missing.append("peer_registry")
    if not HAVE_BOOTSTRAP:
        missing.append("bootstrap")

    return len(missing) == 0, missing
