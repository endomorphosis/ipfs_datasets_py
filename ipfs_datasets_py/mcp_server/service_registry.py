"""P2P Service Registry for MCP++ cross-server discovery.

Allows MCP++ servers to advertise their capabilities and discover peer
servers over the libp2p network. Each server registers a ServiceRecord
containing its peer_id, multiaddrs, service name, and tool list.

Discovery mechanisms:
1. mDNS (local network) — automatic via libp2p
2. DHT (wide-area) — publish/lookup service records in the DHT
3. Bootstrap registry — static list + gossip

Usage:
    registry = ServiceRegistry(p2p_node)
    await registry.advertise("ipfs-accelerate-mcp", tools=["run_model", "infer"])
    peers = await registry.discover("ipfs-datasets-mcp")

Module: ipfs_accelerate_py.mcplusplus_module.service_registry
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("ipfs_datasets.mcp_server.service_registry")

# DHT namespace for MCP++ service records
SERVICE_NAMESPACE = "/mcppp/services/1.0.0"

# How often to re-advertise (seconds)
READVERTISE_INTERVAL = 60.0

# How long a service record is valid (seconds)
SERVICE_TTL = 300.0


@dataclass
class ServiceRecord:
    """A service advertisement published to the P2P network."""
    service_name: str
    peer_id: str
    multiaddrs: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    timestamp: float = field(default_factory=time.time)
    ttl: float = SERVICE_TTL
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """DHT key for this record."""
        return f"{SERVICE_NAMESPACE}/{self.service_name}/{self.peer_id}"

    @property
    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_name": self.service_name,
            "peer_id": self.peer_id,
            "multiaddrs": self.multiaddrs,
            "tools": self.tools,
            "version": self.version,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceRecord":
        return cls(
            service_name=data.get("service_name", ""),
            peer_id=data.get("peer_id", ""),
            multiaddrs=data.get("multiaddrs", []),
            tools=data.get("tools", []),
            version=data.get("version", "1.0.0"),
            timestamp=data.get("timestamp", time.time()),
            ttl=data.get("ttl", SERVICE_TTL),
            metadata=data.get("metadata", {}),
        )


class ServiceRegistry:
    """P2P service registry for MCP++ cross-server discovery.

    Maintains a local cache of discovered services and periodically
    re-advertises our own service record.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._local_records: Dict[str, ServiceRecord] = {}  # Our advertised services
        self._remote_records: Dict[str, Dict[str, ServiceRecord]] = {}  # service_name -> {peer_id -> record}
        self._listeners: List[Any] = []

    def register_local(self, record: ServiceRecord) -> None:
        """Register a local service for advertisement."""
        with self._lock:
            self._local_records[record.service_name] = record
        logger.info(f"Registered local service: {record.service_name} ({len(record.tools)} tools)")

    def add_remote(self, record: ServiceRecord) -> None:
        """Add a discovered remote service record."""
        if record.is_expired:
            return
        with self._lock:
            self._remote_records.setdefault(record.service_name, {})[record.peer_id] = record
        logger.debug(f"Added remote service: {record.service_name} from {record.peer_id}")

    def get_services(self, service_name: Optional[str] = None) -> List[ServiceRecord]:
        """Get all known service records (local + remote), optionally filtered by name."""
        with self._lock:
            results = []
            if service_name:
                for record in self._remote_records.get(service_name, {}).values():
                    if not record.is_expired:
                        results.append(record)
            else:
                for svc_records in self._remote_records.values():
                    for record in svc_records.values():
                        if not record.is_expired:
                            results.append(record)
            return results

    def get_peers_for_tool(self, tool_name: str) -> List[ServiceRecord]:
        """Find all peers that advertise a specific tool."""
        results = []
        with self._lock:
            for svc_records in self._remote_records.values():
                for record in svc_records.values():
                    if not record.is_expired and tool_name in record.tools:
                        results.append(record)
        return results

    def cleanup_stale(self) -> int:
        """Remove expired service records. Returns count removed."""
        removed = 0
        with self._lock:
            for svc_name in list(self._remote_records.keys()):
                stale = [pid for pid, r in self._remote_records[svc_name].items() if r.is_expired]
                for pid in stale:
                    del self._remote_records[svc_name][pid]
                    removed += 1
                if not self._remote_records[svc_name]:
                    del self._remote_records[svc_name]
        return removed

    async def advertise_loop(self, p2p_node, nursery) -> None:
        """Background loop that periodically advertises our services via P2P.

        Sends service records to connected peers via the /mcp+p2p/1.0.0 protocol.
        """
        import trio

        while True:
            try:
                await trio.sleep(READVERTISE_INTERVAL)

                with self._lock:
                    records = list(self._local_records.values())

                for record in records:
                    record.timestamp = time.time()  # Refresh timestamp
                    # Broadcast to all connected peers
                    for peer_id in list(p2p_node._peers.keys()):
                        try:
                            await p2p_node.call_tool(
                                peer_id,
                                "_mcppp_service_announce",
                                {"record": record.to_dict()},
                                timeout=5.0,
                            )
                        except Exception:
                            pass  # Non-critical

                # Cleanup stale entries
                removed = self.cleanup_stale()
                if removed:
                    logger.debug(f"Cleaned up {removed} stale service records")

            except trio.Cancelled:
                break
            except Exception as e:
                logger.debug(f"Service advertise error: {e}")

    def handle_announce(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle an incoming service announcement from a peer."""
        record_data = params.get("record", {})
        if record_data:
            record = ServiceRecord.from_dict(record_data)
            self.add_remote(record)
            return {"status": "accepted", "service": record.service_name}
        return {"status": "rejected", "reason": "empty record"}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize registry state for API responses."""
        with self._lock:
            return {
                "local_services": {k: v.to_dict() for k, v in self._local_records.items()},
                "remote_services": {
                    svc: [r.to_dict() for r in records.values() if not r.is_expired]
                    for svc, records in self._remote_records.items()
                },
                "total_remote_peers": sum(
                    len([r for r in records.values() if not r.is_expired])
                    for records in self._remote_records.values()
                ),
            }


# Singleton
_REGISTRY: Optional[ServiceRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_service_registry() -> ServiceRegistry:
    """Get the global service registry (thread-safe singleton)."""
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = ServiceRegistry()
    return _REGISTRY
