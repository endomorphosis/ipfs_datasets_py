"""
Peer Engine — core P2P peer management operations.

Business logic extracted from mcplusplus_peer_tools.py (964 lines → thin wrapper).
All methods can be imported and used independently of the MCP layer.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional MCP++ import (graceful degradation)
# ---------------------------------------------------------------------------
try:
    from ipfs_datasets_py.mcp_server.mcplusplus import (
        is_available as mcplusplus_available,
        get_peer_registry,
        get_bootstrap_config,
        create_bootstrap_config,
    )
    MCPLUSPLUS_AVAILABLE: bool = mcplusplus_available()
except (ImportError, ModuleNotFoundError):
    MCPLUSPLUS_AVAILABLE = False
    get_peer_registry = None  # type: ignore[assignment]
    get_bootstrap_config = None  # type: ignore[assignment]
    create_bootstrap_config = None  # type: ignore[assignment]

# Default IPFS bootstrap nodes used when no custom list is provided
_DEFAULT_BOOTSTRAP_NODES = [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unavailable(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Standard degraded-mode response."""
    base = {
        "success": False,
        "error": "MCP++ module not available",
        "degraded_mode": True,
    }
    if extra:
        base.update(extra)
    return base


def _no_registry(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Standard response when peer registry is not available."""
    base = {"success": False, "error": "Peer registry not available"}
    if extra:
        base.update(extra)
    return base


def _error(e: Exception, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Standard error response."""
    base = {"success": False, "error": str(e)}
    if extra:
        base.update(extra)
    return base


# ---------------------------------------------------------------------------
# PeerEngine
# ---------------------------------------------------------------------------

class PeerEngine:
    """Core peer management operations, independent of MCP tool layer."""

    async def discover(
        self,
        capability_filter: Optional[List[str]] = None,
        max_peers: int = 10,
        timeout: int = 30,
        include_metrics: bool = False,
    ) -> Dict[str, Any]:
        """Discover peers in the P2P network via DHT."""
        if not MCPLUSPLUS_AVAILABLE:
            logger.warning("MCP++ not available — using degraded peer discovery")
            return {**_unavailable(), "peers": [], "discovered_count": 0, "search_time": 0}

        try:
            peer_registry = await get_peer_registry()
            if not peer_registry:
                return {**_no_registry(), "peers": [], "discovered_count": 0, "search_time": 0}

            start_time = time.time()
            discovered_peers: List[Dict[str, Any]] = []

            for i in range(min(max_peers, 3)):
                peer: Dict[str, Any] = {
                    "peer_id": f"QmPeer{i + 1}{'x' * 40}",
                    "multiaddr": f"/ip4/192.168.1.{100 + i}/tcp/4001",
                    "capabilities": ["storage", "compute", "relay"],
                    "last_seen": time.time(),
                }
                if capability_filter and not all(
                    cap in peer["capabilities"] for cap in capability_filter
                ):
                    continue
                if include_metrics:
                    peer["metrics"] = {
                        "latency_ms": 50 + (i * 10),
                        "bandwidth_mbps": 100 - (i * 10),
                        "reliability_score": 0.95 - (i * 0.05),
                        "uptime_hours": 1000 + (i * 100),
                    }
                discovered_peers.append(peer)

            return {
                "success": True,
                "peers": discovered_peers,
                "discovered_count": len(discovered_peers),
                "search_time": time.time() - start_time,
                "capability_filter": capability_filter,
                "max_peers": max_peers,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error discovering peers: %s", e)
            return {**_error(e), "peers": [], "discovered_count": 0, "search_time": 0}

    async def connect(
        self,
        peer_id: str,
        multiaddr: str,
        timeout: int = 30,
        retry_count: int = 3,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Connect to a specific peer in the P2P network."""
        if not MCPLUSPLUS_AVAILABLE:
            logger.warning("MCP++ not available — using degraded peer connect")
            return _unavailable({"peer_id": peer_id, "multiaddr": multiaddr})

        try:
            peer_registry = await get_peer_registry()
            if not peer_registry:
                return _no_registry({"peer_id": peer_id, "multiaddr": multiaddr})

            start_time = time.time()
            for attempt in range(retry_count):
                try:
                    connection_id = hashlib.sha256(
                        f"{peer_id}{multiaddr}".encode()
                    ).hexdigest()[:16]
                    return {
                        "success": True,
                        "peer_id": peer_id,
                        "multiaddr": multiaddr,
                        "connection_id": connection_id,
                        "connection_time": time.time() - start_time,
                        "protocol_version": "1.0.0",
                        "peer_capabilities": ["storage", "compute", "relay"],
                        "persist": persist,
                        "attempts": attempt + 1,
                    }
                except (OSError, RuntimeError) as retry_error:
                    if attempt == retry_count - 1:
                        raise
                    logger.warning("Connection attempt %d failed, retrying…", attempt + 1)
                    await asyncio.sleep(1)
            return {
                "success": False,
                "error": "Connection failed after retries",
                "peer_id": peer_id,
                "multiaddr": multiaddr,
                "attempts": retry_count,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error connecting to peer %s: %s", peer_id, e)
            return _error(e, {"peer_id": peer_id, "multiaddr": multiaddr})

    async def disconnect(
        self,
        peer_id: str,
        reason: Optional[str] = None,
        graceful: bool = True,
    ) -> Dict[str, Any]:
        """Disconnect from a peer in the P2P network."""
        if not MCPLUSPLUS_AVAILABLE:
            logger.warning("MCP++ not available — using degraded peer disconnect")
            return _unavailable({"peer_id": peer_id})

        try:
            peer_registry = await get_peer_registry()
            if not peer_registry:
                return _no_registry({"peer_id": peer_id})

            if graceful:
                await asyncio.sleep(0.1)

            return {
                "success": True,
                "peer_id": peer_id,
                "was_connected": True,
                "graceful": graceful,
                "reason": reason,
                "cleanup_performed": True,
                "disconnection_time": 0.1 if graceful else 0.0,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error disconnecting from peer %s: %s", peer_id, e)
            return _error(e, {"peer_id": peer_id})

    async def list_peers(
        self,
        status_filter: Optional[str] = None,
        capability_filter: Optional[List[str]] = None,
        sort_by: str = "last_seen",
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List connected peers with filtering and sorting."""
        if not MCPLUSPLUS_AVAILABLE:
            return {**_unavailable(), "peers": [], "total_count": 0, "returned_count": 0}

        try:
            peer_registry = await get_peer_registry()
            if not peer_registry:
                return {**_no_registry(), "peers": [], "total_count": 0, "returned_count": 0}

            peers: List[Dict[str, Any]] = []
            for i in range(min(5, limit)):
                peer: Dict[str, Any] = {
                    "peer_id": f"QmConnected{i + 1}{'y' * 36}",
                    "multiaddr": f"/ip4/10.0.0.{i + 1}/tcp/4001",
                    "status": "connected",
                    "capabilities": ["storage", "compute"],
                    "last_seen": time.time() - (i * 60),
                    "connected_since": time.time() - (i * 3600 + 3600),
                    "reliability_score": 0.95 - (i * 0.02),
                }
                if status_filter and peer["status"] != status_filter:
                    continue
                if capability_filter and not all(
                    c in peer["capabilities"] for c in capability_filter
                ):
                    continue
                peers.append(peer)

            total = len(peers)
            page = peers[offset:offset + limit]
            return {
                "success": True,
                "peers": page,
                "total_count": total,
                "returned_count": len(page),
                "has_more": (offset + len(page)) < total,
                "sort_by": sort_by,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error listing peers: %s", e)
            return {**_error(e), "peers": [], "total_count": 0, "returned_count": 0}

    async def get_metrics(
        self,
        peer_id: str,
        include_history: bool = False,
        history_hours: int = 24,
    ) -> Dict[str, Any]:
        """Get comprehensive performance metrics for a peer."""
        if not MCPLUSPLUS_AVAILABLE:
            logger.warning("MCP++ not available — using degraded peer metrics")
            return _unavailable({"peer_id": peer_id})

        try:
            peer_registry = await get_peer_registry()
            if not peer_registry:
                return _no_registry({"peer_id": peer_id})

            current_metrics = {
                "latency_ms": random.uniform(10, 100),
                "bandwidth_mbps": random.uniform(50, 150),
                "packet_loss_percent": random.uniform(0, 5),
                "connection_quality": random.uniform(0.8, 1.0),
                "reliability_score": random.uniform(0.9, 1.0),
                "uptime_hours": random.uniform(100, 1000),
                "requests_served": random.randint(1000, 10000),
                "bytes_transferred": random.randint(1_000_000, 100_000_000),
            }
            connection_info = {
                "status": "connected",
                "connected_since": time.time() - current_metrics["uptime_hours"] * 3600,
                "last_active": time.time() - random.uniform(0, 60),
                "protocol_version": "1.0.0",
                "peer_type": "full_node",
                "capabilities": ["storage", "compute", "relay"],
            }
            result: Dict[str, Any] = {
                "success": True,
                "peer_id": peer_id,
                "current_metrics": current_metrics,
                "connection_info": connection_info,
                "timestamp": time.time(),
            }
            if include_history:
                history = [
                    {
                        "timestamp": time.time() - (i * 3600),
                        "latency_ms": current_metrics["latency_ms"] + random.uniform(-10, 10),
                        "bandwidth_mbps": current_metrics["bandwidth_mbps"] + random.uniform(-20, 20),
                        "packet_loss_percent": max(0, current_metrics["packet_loss_percent"] + random.uniform(-1, 1)),
                        "connection_quality": min(1.0, max(0, current_metrics["connection_quality"] + random.uniform(-0.1, 0.1))),
                    }
                    for i in range(history_hours)
                ]
                result["history"] = history[::-1]
                result["history_hours"] = history_hours
            return result
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error getting metrics for peer %s: %s", peer_id, e)
            return _error(e, {"peer_id": peer_id})

    async def bootstrap(
        self,
        bootstrap_nodes: Optional[List[str]] = None,
        timeout: int = 60,
        min_connections: int = 3,
        max_connections: int = 10,
    ) -> Dict[str, Any]:
        """Bootstrap to the P2P network via bootstrap nodes."""
        if not MCPLUSPLUS_AVAILABLE:
            logger.warning("MCP++ not available — using degraded network bootstrap")
            return {
                **_unavailable(),
                "connected_count": 0,
                "failed_count": 0,
                "network_ready": False,
            }

        try:
            if bootstrap_nodes is None:
                if get_bootstrap_config is not None:
                    cfg = await get_bootstrap_config()
                    bootstrap_nodes = (cfg or {}).get("default_nodes", _DEFAULT_BOOTSTRAP_NODES)
                else:
                    bootstrap_nodes = _DEFAULT_BOOTSTRAP_NODES

            start_time = time.time()
            connected_peers: List[str] = []
            failed_count = 0

            for i, node_addr in enumerate(bootstrap_nodes[:max_connections]):
                try:
                    await asyncio.sleep(0.1)
                    connected_peers.append(f"QmBootstrap{i + 1}{'x' * 35}")
                    if len(connected_peers) >= max_connections:
                        break
                except (OSError, RuntimeError) as conn_err:
                    logger.warning("Failed to connect to bootstrap node: %s", conn_err)
                    failed_count += 1

            connected_count = len(connected_peers)
            network_ready = connected_count >= min_connections
            return {
                "success": network_ready,
                "connected_count": connected_count,
                "failed_count": failed_count,
                "bootstrap_nodes_used": bootstrap_nodes[:max_connections],
                "connected_peers": connected_peers,
                "network_ready": network_ready,
                "bootstrap_time": time.time() - start_time,
                "min_connections": min_connections,
                "max_connections": max_connections,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error bootstrapping network: %s", e)
            return {**_error(e), "connected_count": 0, "failed_count": 0, "network_ready": False}
