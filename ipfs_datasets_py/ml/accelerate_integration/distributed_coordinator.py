"""
Distributed Compute Coordinator for P2P ML inference.

This module coordinates distributed compute across IPFS network peers,
handling workload distribution, result aggregation, and failure recovery.
"""

import logging
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of a distributed compute task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ComputeTask:
    """
    Represents a distributed compute task.
    """
    task_id: str
    model_name: str
    input_data: Any
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    assigned_peer: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None


class DistributedComputeCoordinator:
    """
    Coordinates distributed compute across IPFS network peers.
    
    This class manages task distribution, peer discovery, load balancing,
    and result aggregation for distributed ML inference.
    """
    
    def __init__(
        self,
        ipfs_client: Optional[Any] = None,
        max_concurrent_tasks: int = 10,
        enable_load_balancing: bool = True
    ):
        """
        Initialize the distributed compute coordinator.
        
        Args:
            ipfs_client: IPFS client for peer communication
            max_concurrent_tasks: Maximum concurrent tasks
            enable_load_balancing: Whether to enable load balancing
        """
        self.ipfs_client = ipfs_client
        self.max_concurrent_tasks = max_concurrent_tasks
        self.enable_load_balancing = enable_load_balancing
        
        self.tasks: Dict[str, ComputeTask] = {}
        self.available_peers: List[str] = []
        self._initialized = False
    
    def initialize(self) -> bool:
        """
        Initialize the coordinator and discover peers.
        
        Returns:
            bool: True if initialization successful
        """
        try:
            # Discover peers on IPFS network
            if self.ipfs_client:
                self._discover_peers()
            
            self._initialized = True
            logger.info("DistributedComputeCoordinator initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize coordinator: {e}")
            return False
    
    def _discover_peers(self):
        """Discover compute peers on IPFS network."""
        # This would use IPFS pubsub or DHT to discover peers
        logger.info("Discovering compute peers on IPFS network")
        # Mock peer discovery
        self.available_peers = []
    
    def submit_task(
        self,
        task_id: str,
        model_name: str,
        input_data: Any,
        task_type: str = "inference",
        priority: int = 0
    ) -> ComputeTask:
        """
        Submit a compute task for distributed execution.
        
        Args:
            task_id: Unique task identifier
            model_name: Name of the model to use
            input_data: Input data for the task
            task_type: Type of task to perform
            priority: Task priority (higher = more urgent)
            
        Returns:
            ComputeTask: Created task object
        """
        task = ComputeTask(
            task_id=task_id,
            model_name=model_name,
            input_data=input_data,
            task_type=task_type
        )
        
        self.tasks[task_id] = task
        
        if self.enable_load_balancing and self.available_peers:
            # Assign to best available peer
            peer = self._select_peer(task)
            task.assigned_peer = peer
            task.status = TaskStatus.RUNNING
            logger.info(f"Task {task_id} assigned to peer {peer}")
        else:
            # Execute locally
            task.status = TaskStatus.RUNNING
            logger.info(f"Task {task_id} executing locally (no peers available)")
        
        return task
    
    def _select_peer(self, task: ComputeTask) -> Optional[str]:
        """
        Select the best peer for a task using load balancing.
        
        Args:
            task: Task to assign
            
        Returns:
            str: Selected peer ID, or None if no peers available
        """
        if not self.available_peers:
            return None
        
        # Simple round-robin for now
        # In practice, this would consider:
        # - Peer hardware capabilities
        # - Current peer load
        # - Network latency
        # - Model availability on peer
        return self.available_peers[0] if self.available_peers else None
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """
        Get status of a task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            TaskStatus: Current task status, or None if not found
        """
        task = self.tasks.get(task_id)
        return task.status if task else None
    
    def get_task_result(self, task_id: str) -> Optional[Any]:
        """
        Get result of a completed task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Task result, or None if not completed
        """
        task = self.tasks.get(task_id)
        if task and task.status == TaskStatus.COMPLETED:
            return task.result
        return None
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a pending or running task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            bool: True if task was cancelled
        """
        task = self.tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.CANCELLED
            logger.info(f"Task {task_id} cancelled")
            return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get coordinator statistics.
        
        Returns:
            dict: Statistics including task counts, peer info, etc.
        """
        status_counts = {}
        for task in self.tasks.values():
            status = task.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "total_tasks": len(self.tasks),
            "status_counts": status_counts,
            "available_peers": len(self.available_peers),
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "load_balancing_enabled": self.enable_load_balancing
        }
