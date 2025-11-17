"""
P2P Workflow Scheduler for Decentralized GitHub Actions

Implements a peer-to-peer workflow scheduling system that bypasses GitHub API
for non-critical workflows using merkle clock consensus and fibonacci heap prioritization.

Features:
- Merkle clock for distributed consensus
- Fibonacci heap for workflow prioritization  
- Hamming distance for peer task assignment
- Workflow tagging to identify P2P-eligible workflows
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Set, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class WorkflowTag(Enum):
    """Tags to identify workflow execution modes."""
    GITHUB_API = "github_api"  # Use GitHub API (default)
    P2P_ELIGIBLE = "p2p_eligible"  # Can be executed via P2P
    P2P_ONLY = "p2p_only"  # Must be executed via P2P (bypass GitHub completely)
    UNIT_TEST = "unit_test"  # Unit test workflow (GitHub API)
    CODE_GEN = "code_gen"  # Code generation workflow (P2P eligible)
    WEB_SCRAPE = "web_scrape"  # Web scraping workflow (P2P eligible)
    DATA_PROCESSING = "data_processing"  # Data processing (P2P eligible)


@dataclass
class MerkleClock:
    """
    Merkle clock for distributed consensus.
    
    Uses content-addressable hashing to establish causal ordering
    and detect concurrent events in distributed systems.
    """
    peer_id: str
    counter: int = 0
    parent_hash: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    def tick(self) -> 'MerkleClock':
        """Increment the clock and generate new hash."""
        new_clock = MerkleClock(
            peer_id=self.peer_id,
            counter=self.counter + 1,
            parent_hash=self.hash(),
            timestamp=time.time()
        )
        return new_clock
    
    def hash(self) -> str:
        """Generate content-addressable hash of clock state."""
        content = f"{self.peer_id}:{self.counter}:{self.parent_hash}:{self.timestamp}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def merge(self, other: 'MerkleClock') -> 'MerkleClock':
        """
        Merge two merkle clocks (for handling concurrent events).
        
        Takes the maximum counter and creates a new clock that
        references both parent clocks.
        """
        new_counter = max(self.counter, other.counter) + 1
        # Combine both parent hashes for merge node
        combined_parent = f"{self.hash()}:{other.hash()}"
        parent_hash = hashlib.sha256(combined_parent.encode()).hexdigest()
        
        return MerkleClock(
            peer_id=self.peer_id,
            counter=new_counter,
            parent_hash=parent_hash,
            timestamp=time.time()
        )
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            'peer_id': self.peer_id,
            'counter': self.counter,
            'parent_hash': self.parent_hash,
            'timestamp': self.timestamp,
            'hash': self.hash()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'MerkleClock':
        """Deserialize from dictionary."""
        return cls(
            peer_id=data['peer_id'],
            counter=data['counter'],
            parent_hash=data.get('parent_hash'),
            timestamp=data.get('timestamp', time.time())
        )


class FibonacciHeap:
    """
    Fibonacci heap for efficient priority queue operations.
    
    Provides O(1) insertion and O(log n) extract-min operations,
    ideal for workflow scheduling with dynamic priorities.
    """
    
    @dataclass
    class Node:
        """Fibonacci heap node."""
        key: float  # Priority value (lower = higher priority)
        value: Any  # Workflow data
        degree: int = 0
        marked: bool = False
        parent: Optional['FibonacciHeap.Node'] = None
        child: Optional['FibonacciHeap.Node'] = None
        left: Optional['FibonacciHeap.Node'] = None
        right: Optional['FibonacciHeap.Node'] = None
    
    def __init__(self):
        self.min_node: Optional[FibonacciHeap.Node] = None
        self.num_nodes: int = 0
    
    def is_empty(self) -> bool:
        """Check if heap is empty."""
        return self.min_node is None
    
    def insert(self, key: float, value: Any) -> 'FibonacciHeap.Node':
        """
        Insert a new node with given priority.
        
        Args:
            key: Priority value (lower = higher priority)
            value: Workflow data
            
        Returns:
            The created node
        """
        node = self.Node(key=key, value=value)
        node.left = node
        node.right = node
        
        if self.min_node is None:
            self.min_node = node
        else:
            self._insert_into_root_list(node)
            if node.key < self.min_node.key:
                self.min_node = node
        
        self.num_nodes += 1
        return node
    
    def find_min(self) -> Optional[Tuple[float, Any]]:
        """
        Find minimum priority element without removing it.
        
        Returns:
            Tuple of (priority, workflow) or None if empty
        """
        if self.min_node is None:
            return None
        return (self.min_node.key, self.min_node.value)
    
    def extract_min(self) -> Optional[Tuple[float, Any]]:
        """
        Extract and return minimum priority element.
        
        Returns:
            Tuple of (priority, workflow) or None if empty
        """
        z = self.min_node
        if z is None:
            return None
        
        # Add all children to root list
        if z.child is not None:
            child = z.child
            while True:
                next_child = child.right
                self._insert_into_root_list(child)
                child.parent = None
                child = next_child
                if child == z.child:
                    break
        
        # Remove z from root list
        z.left.right = z.right
        z.right.left = z.left
        
        if z == z.right:
            self.min_node = None
        else:
            self.min_node = z.right
            self._consolidate()
        
        self.num_nodes -= 1
        return (z.key, z.value)
    
    def _insert_into_root_list(self, node: 'FibonacciHeap.Node'):
        """Insert node into root list."""
        if self.min_node is None:
            self.min_node = node
            node.left = node
            node.right = node
        else:
            node.left = self.min_node
            node.right = self.min_node.right
            self.min_node.right.left = node
            self.min_node.right = node
    
    def _consolidate(self):
        """Consolidate heap after extract-min."""
        max_degree = int(self.num_nodes ** 0.5) + 1
        degree_table = [None] * max_degree
        
        # Collect all root nodes
        roots = []
        if self.min_node is not None:
            node = self.min_node
            while True:
                roots.append(node)
                node = node.right
                if node == self.min_node:
                    break
        
        # Consolidate roots
        for root in roots:
            degree = root.degree
            while degree < len(degree_table) and degree_table[degree] is not None:
                other = degree_table[degree]
                if root.key > other.key:
                    root, other = other, root
                self._link(other, root)
                degree_table[degree] = None
                degree += 1
            
            if degree < len(degree_table):
                degree_table[degree] = root
        
        # Rebuild root list and find new minimum
        self.min_node = None
        for node in degree_table:
            if node is not None:
                if self.min_node is None:
                    self.min_node = node
                    node.left = node
                    node.right = node
                else:
                    self._insert_into_root_list(node)
                    if node.key < self.min_node.key:
                        self.min_node = node
    
    def _link(self, child: 'FibonacciHeap.Node', parent: 'FibonacciHeap.Node'):
        """Link child node to parent."""
        # Remove child from root list
        child.left.right = child.right
        child.right.left = child.left
        
        # Make child a child of parent
        child.parent = parent
        if parent.child is None:
            parent.child = child
            child.left = child
            child.right = child
        else:
            child.left = parent.child
            child.right = parent.child.right
            parent.child.right.left = child
            parent.child.right = child
        
        parent.degree += 1
        child.marked = False
    
    def size(self) -> int:
        """Get number of elements in heap."""
        return self.num_nodes


@dataclass
class WorkflowDefinition:
    """Definition of a workflow to be scheduled."""
    workflow_id: str
    name: str
    tags: List[WorkflowTag]
    priority: float = 1.0  # Lower = higher priority
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_p2p_eligible(self) -> bool:
        """Check if workflow can be executed via P2P."""
        return (
            WorkflowTag.P2P_ELIGIBLE in self.tags or
            WorkflowTag.P2P_ONLY in self.tags
        )
    
    def requires_github_api(self) -> bool:
        """Check if workflow requires GitHub API."""
        return WorkflowTag.GITHUB_API in self.tags or WorkflowTag.UNIT_TEST in self.tags
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            'workflow_id': self.workflow_id,
            'name': self.name,
            'tags': [tag.value for tag in self.tags],
            'priority': self.priority,
            'created_at': self.created_at,
            'metadata': self.metadata
        }


def calculate_hamming_distance(hash1: str, hash2: str) -> int:
    """
    Calculate hamming distance between two hex hash strings.
    
    Args:
        hash1: First hash (hex string)
        hash2: Second hash (hex string)
        
    Returns:
        Number of differing bits
    """
    # Convert hex to binary
    bin1 = bin(int(hash1, 16))[2:].zfill(len(hash1) * 4)
    bin2 = bin(int(hash2, 16))[2:].zfill(len(hash2) * 4)
    
    # Count differing bits
    return sum(b1 != b2 for b1, b2 in zip(bin1, bin2))


class P2PWorkflowScheduler:
    """
    P2P Workflow Scheduler using merkle clock consensus and fibonacci heap prioritization.
    
    Enables distributed workflow execution that bypasses GitHub API by:
    1. Using merkle clock for distributed consensus on task ownership
    2. Calculating hamming distance to determine which peer handles each task
    3. Using fibonacci heap for efficient workflow prioritization
    """
    
    def __init__(
        self,
        peer_id: str,
        peers: Optional[List[str]] = None
    ):
        """
        Initialize P2P workflow scheduler.
        
        Args:
            peer_id: This peer's identifier
            peers: List of known peer IDs in the network
        """
        self.peer_id = peer_id
        self.peers = set(peers or [])
        self.peers.add(peer_id)  # Include self
        
        # Merkle clock for consensus
        self.clock = MerkleClock(peer_id=peer_id)
        
        # Fibonacci heap for workflow prioritization
        self.workflow_queue = FibonacciHeap()
        
        # Workflow registry
        self.workflows: Dict[str, WorkflowDefinition] = {}
        self.assigned_workflows: Set[str] = set()  # Workflows assigned to this peer
        
        logger.info(f"Initialized P2P workflow scheduler for peer {peer_id}")
        logger.info(f"  Known peers: {len(self.peers)}")
    
    def add_peer(self, peer_id: str):
        """Add a new peer to the network."""
        self.peers.add(peer_id)
        logger.info(f"Added peer {peer_id}, total peers: {len(self.peers)}")
    
    def remove_peer(self, peer_id: str):
        """Remove a peer from the network."""
        if peer_id in self.peers and peer_id != self.peer_id:
            self.peers.remove(peer_id)
            logger.info(f"Removed peer {peer_id}, remaining peers: {len(self.peers)}")
    
    def schedule_workflow(
        self,
        workflow: WorkflowDefinition
    ) -> Dict[str, Any]:
        """
        Schedule a workflow for execution.
        
        Determines if this peer should execute the workflow based on
        hamming distance calculation.
        
        Args:
            workflow: Workflow definition to schedule
            
        Returns:
            Dictionary with scheduling result
        """
        # Check if workflow is P2P eligible
        if not workflow.is_p2p_eligible():
            return {
                'success': False,
                'workflow_id': workflow.workflow_id,
                'reason': 'Workflow requires GitHub API',
                'tags': [tag.value for tag in workflow.tags]
            }
        
        # Tick merkle clock
        self.clock = self.clock.tick()
        
        # Calculate which peer should handle this workflow
        assigned_peer = self._determine_responsible_peer(workflow)
        
        # Store workflow
        self.workflows[workflow.workflow_id] = workflow
        
        # If this peer is responsible, add to queue
        if assigned_peer == self.peer_id:
            self.workflow_queue.insert(workflow.priority, workflow)
            self.assigned_workflows.add(workflow.workflow_id)
            
            logger.info(
                f"Workflow {workflow.workflow_id} assigned to this peer "
                f"(priority: {workflow.priority})"
            )
            
            return {
                'success': True,
                'workflow_id': workflow.workflow_id,
                'assigned_peer': assigned_peer,
                'is_local': True,
                'queue_size': self.workflow_queue.size(),
                'clock_hash': self.clock.hash()
            }
        else:
            logger.info(
                f"Workflow {workflow.workflow_id} assigned to peer {assigned_peer}"
            )
            
            return {
                'success': True,
                'workflow_id': workflow.workflow_id,
                'assigned_peer': assigned_peer,
                'is_local': False,
                'clock_hash': self.clock.hash()
            }
    
    def _determine_responsible_peer(
        self,
        workflow: WorkflowDefinition
    ) -> str:
        """
        Determine which peer should execute the workflow.
        
        Uses hamming distance between:
        - hash(merkle_clock_head) + hash(task)
        - hash(peer_id)
        
        The peer with minimum hamming distance is responsible.
        
        Args:
            workflow: Workflow to assign
            
        Returns:
            Peer ID responsible for the workflow
        """
        # Generate task hash
        task_content = f"{workflow.workflow_id}:{workflow.name}:{workflow.created_at}"
        task_hash = hashlib.sha256(task_content.encode()).hexdigest()
        
        # Combine clock head hash and task hash
        clock_hash = self.clock.hash()
        combined_hash = hashlib.sha256(
            f"{clock_hash}:{task_hash}".encode()
        ).hexdigest()
        
        # Calculate hamming distance to each peer
        min_distance = float('inf')
        responsible_peer = self.peer_id
        
        for peer_id in self.peers:
            peer_hash = hashlib.sha256(peer_id.encode()).hexdigest()
            distance = calculate_hamming_distance(combined_hash, peer_hash)
            
            logger.debug(
                f"Hamming distance for peer {peer_id}: {distance}"
            )
            
            if distance < min_distance:
                min_distance = distance
                responsible_peer = peer_id
        
        logger.info(
            f"Workflow {workflow.workflow_id} assigned to {responsible_peer} "
            f"(distance: {min_distance})"
        )
        
        return responsible_peer
    
    def get_next_workflow(self) -> Optional[WorkflowDefinition]:
        """
        Get next workflow to execute from the priority queue.
        
        Returns:
            Next workflow or None if queue is empty
        """
        result = self.workflow_queue.extract_min()
        if result is None:
            return None
        
        priority, workflow = result
        logger.info(f"Dequeued workflow {workflow.workflow_id} (priority: {priority})")
        
        return workflow
    
    def get_queue_size(self) -> int:
        """Get number of workflows in queue."""
        return self.workflow_queue.size()
    
    def get_assigned_workflows(self) -> List[str]:
        """Get list of workflow IDs assigned to this peer."""
        return list(self.assigned_workflows)
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get scheduler status.
        
        Returns:
            Dictionary with scheduler state
        """
        return {
            'peer_id': self.peer_id,
            'num_peers': len(self.peers),
            'clock': self.clock.to_dict(),
            'queue_size': self.workflow_queue.size(),
            'assigned_workflows': len(self.assigned_workflows),
            'total_workflows': len(self.workflows)
        }
    
    def merge_clock(self, other_clock: MerkleClock):
        """
        Merge another peer's clock into ours.
        
        Used for synchronization when peers communicate.
        
        Args:
            other_clock: Clock from another peer
        """
        self.clock = self.clock.merge(other_clock)
        logger.debug(f"Merged clock, new hash: {self.clock.hash()}")


# Global scheduler instance
_scheduler_instance: Optional[P2PWorkflowScheduler] = None


def get_scheduler(
    peer_id: Optional[str] = None,
    peers: Optional[List[str]] = None
) -> P2PWorkflowScheduler:
    """
    Get or create global scheduler instance.
    
    Args:
        peer_id: This peer's identifier (auto-generated if None)
        peers: List of known peer IDs
        
    Returns:
        Global P2PWorkflowScheduler instance
    """
    global _scheduler_instance
    
    if _scheduler_instance is None:
        if peer_id is None:
            # Generate peer ID from hostname or random
            import socket
            try:
                peer_id = socket.gethostname()
            except Exception:
                import uuid
                peer_id = f"peer_{uuid.uuid4().hex[:8]}"
        
        _scheduler_instance = P2PWorkflowScheduler(peer_id=peer_id, peers=peers)
    
    return _scheduler_instance
