# ipfs_datasets_py/mcp_server/tools/ipfs_cluster_tools/enhanced_ipfs_cluster_tools.py
"""
Enhanced IPFS cluster tools — standalone async MCP functions.

Business logic (MockIPFSClusterService) lives in
ipfs_datasets_py.ipfs_cluster.cluster_engine.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Import engine from core package (re-export for backward compat)
from ipfs_datasets_py.ipfs_cluster.cluster_engine import MockIPFSClusterService  # noqa: F401

logger = logging.getLogger(__name__)

_DEFAULT_CLUSTER_SERVICE = MockIPFSClusterService()


async def manage_ipfs_cluster(
    action: str,
    node_id: Optional[str] = None,
    cid: Optional[str] = None,
    replication_factor: int = 3,
    cluster_config: Optional[Dict[str, Any]] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute IPFS cluster management operations."""
    cluster_config = cluster_config or {}
    filters = filters or {}

    if action == "status":
        result = await _DEFAULT_CLUSTER_SERVICE.get_cluster_status()
    elif action == "add_node":
        result = await _DEFAULT_CLUSTER_SERVICE.add_node(cluster_config)
    elif action == "remove_node":
        result = await _DEFAULT_CLUSTER_SERVICE.remove_node(node_id)
    elif action == "pin_content":
        result = await _DEFAULT_CLUSTER_SERVICE.pin_content(cid, replication_factor)
    elif action == "unpin_content":
        result = await _DEFAULT_CLUSTER_SERVICE.unpin_content(cid)
    elif action == "list_pins":
        result = await _DEFAULT_CLUSTER_SERVICE.list_pins(filters.get("status"))
    elif action == "sync":
        result = await _DEFAULT_CLUSTER_SERVICE.sync_cluster()
    elif action == "health_check":
        status_result = await _DEFAULT_CLUSTER_SERVICE.get_cluster_status()
        result = {
            "overall_health": status_result.get("cluster_health", "unknown"),
            "node_count": status_result.get("total_nodes", 0),
            "online_nodes": status_result.get("online_nodes", 0),
            "pin_count": status_result.get("total_pins", 0),
            "check_timestamp": datetime.now(timezone.utc).isoformat(),
            "issues": [],
        }
        if result["online_nodes"] < result["node_count"]:
            result["issues"].append("Some nodes are offline")
    elif action == "rebalance":
        result = {"status": "rebalanced", "moved_pins": 5, "rebalance_time_ms": 2000}
    elif action == "backup_state":
        result = {
            "status": "backed_up",
            "backup_size_mb": 10.5,
            "backup_location": "/tmp/cluster_backup.json",
            "backup_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    else:
        result = {"status": "unknown_action", "action": action}

    return {
        "action": action,
        "result": result,
        "status": "success",
        "cluster_operation": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "processing_time_ms": 50,
    }


async def manage_ipfs_content(
    action: str,
    cid: Optional[str] = None,
    content: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    pin: bool = True,
    content_type: str = "text/plain",
) -> Dict[str, Any]:
    """Execute IPFS content operations (upload, download, metadata, verify, list)."""
    metadata = metadata or {}

    if action == "upload":
        if not content:
            raise ValueError("content is required for upload action")
        mock_cid = f"Qm{hashlib.sha256(content.encode()).hexdigest()[:44]}"
        result: Dict[str, Any] = {
            "cid": mock_cid,
            "size_bytes": len(content),
            "content_type": content_type,
            "pinned": pin,
            "upload_time_ms": 150,
        }
        if pin:
            await _DEFAULT_CLUSTER_SERVICE.pin_content(mock_cid)
    elif action == "download":
        result = {"cid": cid, "content": f"Mock content for {cid}", "size_bytes": 1024, "content_type": "text/plain", "download_time_ms": 80}
    elif action == "get_metadata":
        result = {"cid": cid, "metadata": {"size": 1024, "type": "file", "created": datetime.now(timezone.utc).isoformat(), "links": 0}, "retrieval_time_ms": 30}
    elif action == "verify_integrity":
        result = {"cid": cid, "integrity_valid": True, "hash_matches": True, "size_correct": True, "verification_time_ms": 200}
    elif action == "list_content":
        result = {"content": [{"cid": "QmExample1", "size": 1024, "type": "file"}, {"cid": "QmExample2", "size": 2048, "type": "directory"}], "total_items": 2, "list_time_ms": 100}
    else:
        result = {"status": "unknown_action", "action": action}

    return {"action": action, "result": result, "status": "success", "timestamp": datetime.now(timezone.utc).isoformat()}


# Backward-compatible class shims
class EnhancedIPFSClusterManagementTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await manage_ipfs_cluster(parameters["action"], parameters.get("node_id"), parameters.get("cid"), parameters.get("replication_factor", 3), parameters.get("cluster_config", {}), parameters.get("filters", {}))


class EnhancedIPFSContentTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await manage_ipfs_content(parameters["action"], parameters.get("cid"), parameters.get("content"), parameters.get("metadata", {}), parameters.get("pin", True), parameters.get("content_type", "text/plain"))


# Module-level tool instances for registration (backward compat)
enhanced_ipfs_cluster_management_tool = EnhancedIPFSClusterManagementTool()
enhanced_ipfs_content_tool = EnhancedIPFSContentTool()

__all__ = [
    "manage_ipfs_cluster",
    "manage_ipfs_content",
    "EnhancedIPFSClusterManagementTool",
    "EnhancedIPFSContentTool",
    "MockIPFSClusterService",
    "enhanced_ipfs_cluster_management_tool",
    "enhanced_ipfs_content_tool",
]
