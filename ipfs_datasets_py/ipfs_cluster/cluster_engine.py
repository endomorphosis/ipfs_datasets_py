"""
IPFS Cluster Engine — core IPFS cluster business logic.

Domain models and the mock cluster service used by cluster tools.
Extracted from mcp_server/tools/ipfs_cluster_tools/enhanced_ipfs_cluster_tools.py.

Reusable by:
- MCP server tools (mcp_server/tools/ipfs_cluster_tools/)
- CLI commands
- Direct Python imports: from ipfs_datasets_py.ipfs_cluster.cluster_engine import MockIPFSClusterService
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class MockIPFSClusterService:
    """Mock IPFS cluster service for development and testing."""
    
    def __init__(self):
        self.nodes = {
            'node_1': {
                'id': 'QmNodeId1',
                'status': 'online',
                'peer_count': 5,
                'last_seen': datetime.utcnow(),
                'version': '0.14.0'
            },
            'node_2': {
                'id': 'QmNodeId2', 
                'status': 'online',
                'peer_count': 3,
                'last_seen': datetime.utcnow(),
                'version': '0.14.0'
            }
        }
        self.pins = {}
        self.cluster_config = {
            'consensus': 'raft',
            'replication_factor': 3,
            'bootstrap_peers': []
        }
    
    async def get_cluster_status(self) -> Dict[str, Any]:
        """Get overall cluster status."""
        online_nodes = [n for n in self.nodes.values() if n['status'] == 'online']
        return {
            'total_nodes': len(self.nodes),
            'online_nodes': len(online_nodes),
            'consensus': self.cluster_config['consensus'],
            'total_pins': len(self.pins),
            'cluster_health': 'healthy' if len(online_nodes) > 0 else 'degraded'
        }
    
    async def add_node(self, node_config: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new node to the cluster."""
        node_id = f"node_{len(self.nodes) + 1}"
        self.nodes[node_id] = {
            'id': f"QmNodeId{len(self.nodes) + 1}",
            'status': 'online',
            'peer_count': 0,
            'last_seen': datetime.utcnow(),
            'version': '0.14.0',
            'config': node_config
        }
        return {'status': 'added', 'node_id': node_id}
    
    async def remove_node(self, node_id: str) -> Dict[str, Any]:
        """Remove a node from the cluster."""
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} not found")
        
        del self.nodes[node_id]
        return {'status': 'removed', 'node_id': node_id}
    
    async def pin_content(self, cid: str, replication_factor: int = 3) -> Dict[str, Any]:
        """Pin content across cluster nodes."""
        self.pins[cid] = {
            'cid': cid,
            'replication_factor': replication_factor,
            'pinned_nodes': list(self.nodes.keys())[:replication_factor],
            'created_at': datetime.utcnow(),
            'status': 'pinned'
        }
        return {'status': 'pinned', 'cid': cid, 'replicas': replication_factor}
    
    async def unpin_content(self, cid: str) -> Dict[str, Any]:
        """Unpin content from cluster."""
        if cid in self.pins:
            del self.pins[cid]
            return {'status': 'unpinned', 'cid': cid}
        else:
            return {'status': 'not_found', 'cid': cid}
    
    async def list_pins(self, status_filter: Optional[str] = None) -> Dict[str, Any]:
        """List all pins in the cluster."""
        pins = list(self.pins.values())
        if status_filter:
            pins = [p for p in pins if p['status'] == status_filter]
        
        return {'pins': pins, 'total': len(pins)}
    
    async def sync_cluster(self) -> Dict[str, Any]:
        """Synchronize cluster state."""
        # Mock sync operation
        return {
            'status': 'synced',
            'synced_nodes': len(self.nodes),
            'sync_time_ms': 100
        }

