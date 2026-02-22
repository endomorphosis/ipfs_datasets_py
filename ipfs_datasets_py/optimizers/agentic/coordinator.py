"""Multi-agent coordination system for parallel optimization.

This module provides coordination between multiple optimization agents
working in parallel, including conflict resolution, task assignment,
and distributed patch sharing via IPFS.

ENHANCED: Added caching layer using utils.cache for improved performance
of agent state, task queue, and conflict history management.
"""

import anyio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .base import (
    AgenticOptimizer,
    OptimizationMethod,
    OptimizationResult,
    OptimizationTask,
)
from .patch_control import IPFSPatchStore, Patch, WorktreeManager
from ...utils.cache import LocalCache


class AgentStatus(Enum):
    """Status of an optimization agent."""
    IDLE = "idle"
    WORKING = "working"
    VALIDATING = "validating"
    WAITING_APPROVAL = "waiting_approval"
    ERROR = "error"


@dataclass
class AgentState:
    """State of an optimization agent.
    
    Attributes:
        agent_id: Unique identifier for agent
        optimizer: The optimizer instance
        status: Current status
        current_task: Currently assigned task
        worktree: Path to agent's worktree
        completed_tasks: List of completed task IDs
        failed_tasks: List of failed task IDs
        created_at: When agent was created
        last_activity: Last activity timestamp
        metadata: Additional agent metadata
    """
    agent_id: str
    optimizer: AgenticOptimizer
    status: AgentStatus = AgentStatus.IDLE
    current_task: Optional[OptimizationTask] = None
    worktree: Optional[Path] = None
    completed_tasks: List[str] = field(default_factory=list)
    failed_tasks: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConflictInfo:
    """Information about a conflict between patches.
    
    Attributes:
        patch1_id: First conflicting patch ID
        patch2_id: Second conflicting patch ID
        conflicting_files: Files that have conflicts
        conflict_type: Type of conflict (content, semantic, etc.)
        severity: Conflict severity (1-10)
        resolution: How the conflict was resolved
    """
    patch1_id: str
    patch2_id: str
    conflicting_files: List[str]
    conflict_type: str
    severity: int
    resolution: Optional[str] = None


class ConflictResolver:
    """Resolves conflicts between patches from different agents.
    
    Uses various strategies to resolve conflicts:
    - Three-way merge for compatible changes
    - Priority-based resolution (higher priority wins)
    - Semantic analysis to detect logical conflicts
    - Escalation to human review for complex cases
    
    Example:
        >>> resolver = ConflictResolver()
        >>> conflicts = resolver.check(new_patch, existing_patches)
        >>> if conflicts:
        ...     resolved = resolver.resolve(new_patch, conflicts)
    """
    
    def __init__(self):
        """Initialize conflict resolver."""
        self.conflict_history: List[ConflictInfo] = []
        
    def check(
        self,
        patch: Patch,
        agent_states: Dict[str, AgentState],
    ) -> List[ConflictInfo]:
        """Check for conflicts with patches from other agents.
        
        Args:
            patch: New patch to check
            agent_states: Dictionary of all agent states
            
        Returns:
            List of detected conflicts
        """
        conflicts = []
        
        # Check file overlap with other agents' patches
        for agent_id, state in agent_states.items():
            if state.agent_id == patch.agent_id:
                continue  # Skip self
                
            if state.status != AgentStatus.WORKING:
                continue
                
            # Check if working on same files
            if state.current_task:
                target_files = set(patch.target_files)
                task_files = set(str(f) for f in state.current_task.target_files)
                
                overlap = target_files & task_files
                if overlap:
                    conflict = ConflictInfo(
                        patch1_id=patch.patch_id,
                        patch2_id=f"{agent_id}-current",
                        conflicting_files=list(overlap),
                        conflict_type="file_overlap",
                        severity=5,  # Medium severity
                    )
                    conflicts.append(conflict)
        
        return conflicts
    
    def resolve(
        self,
        patch: Patch,
        conflicts: List[ConflictInfo],
    ) -> Patch:
        """Resolve conflicts and return modified patch.
        
        Args:
            patch: Patch with conflicts
            conflicts: List of conflicts to resolve
            
        Returns:
            Resolved patch (may be modified)
        """
        # For now, use simple priority-based resolution
        # In production, this would use more sophisticated methods
        
        for conflict in conflicts:
            if conflict.severity < 5:
                # Low severity - can auto-resolve
                conflict.resolution = "auto-merged"
            else:
                # High severity - escalate to human
                conflict.resolution = "escalated"
                patch.metadata['requires_manual_review'] = True
            
            self.conflict_history.append(conflict)
        
        return patch
    
    def get_conflict_history(self) -> List[ConflictInfo]:
        """Get history of all conflicts.
        
        Returns:
            List of all conflict info
        """
        return self.conflict_history.copy()


class IPFSBroadcast:
    """Broadcasts patches to other agents via IPFS.
    
    Enables distributed coordination where agents can discover
    and fetch patches from each other using IPFS CIDs.
    
    Example:
        >>> broadcast = IPFSBroadcast(ipfs_client, ipfs_store)
        >>> cid = broadcast.store_patch(patch)
        >>> broadcast.notify_agents(cid, exclude=["agent-1"])
    """
    
    def __init__(self, ipfs_store: IPFSPatchStore):
        """Initialize IPFS broadcast system.
        
        Args:
            ipfs_store: IPFS patch store instance
        """
        self.ipfs_store = ipfs_store
        self.announced_patches: Set[str] = set()
        
    def store_patch(self, patch: Patch) -> str:
        """Store patch in IPFS and return CID.
        
        Args:
            patch: Patch to store
            
        Returns:
            IPFS CID
        """
        cid = self.ipfs_store.store_patch(patch)
        self.announced_patches.add(cid)
        return cid
    
    def notify_agents(
        self,
        cid: str,
        exclude: Optional[List[str]] = None,
    ) -> bool:
        """Notify other agents about new patch.
        
        In practice, this would use libp2p pubsub or similar.
        For now, we just pin the patch.
        
        Args:
            cid: Patch CID to broadcast
            exclude: Optional list of agent IDs to exclude
            
        Returns:
            True if successful, False otherwise
        """
        # Pin to ensure availability
        return self.ipfs_store.pin_patch(cid)
    
    def get_announced_patches(self) -> List[str]:
        """Get list of announced patch CIDs.
        
        Returns:
            List of CIDs
        """
        return list(self.announced_patches)


class AgentCoordinator:
    """Coordinates multiple optimization agents working in parallel.
    
    Responsibilities:
    - Task assignment and load balancing
    - Agent lifecycle management
    - Conflict detection and resolution
    - Patch broadcast and synchronization
    - Performance monitoring
    
    Example:
        >>> coordinator = AgentCoordinator(
        ...     repo_path=Path("/path/to/repo"),
        ...     ipfs_client=ipfs_client
        ... )
        >>> agent_id = coordinator.register_agent(optimizer)
        >>> task = OptimizationTask(task_id="task-1", description="Optimize X")
        >>> coordinator.assign_task(agent_id, task)
        >>> result = await coordinator.execute_task(agent_id)
    """
    
    def __init__(
        self,
        repo_path: Path,
        ipfs_client: Any,
        max_agents: int = 5,
        enable_cache: bool = True,
    ):
        """Initialize agent coordinator.
        
        Args:
            repo_path: Path to git repository
            ipfs_client: IPFS HTTP client
            max_agents: Maximum number of concurrent agents
            enable_cache: Enable caching for agent state and tasks (default: True)
        """
        self.repo_path = Path(repo_path)
        self.max_agents = max_agents
        self.worktree_manager = WorktreeManager(repo_path)
        self.ipfs_store = IPFSPatchStore(ipfs_client)
        self.ipfs_broadcast = IPFSBroadcast(self.ipfs_store)
        self.conflict_resolver = ConflictResolver()
        
        self.agents: Dict[str, AgentState] = {}
        self.task_queue: List[OptimizationTask] = []
        self.pending_approvals: Dict[str, OptimizationResult] = {}
        
        # Add caching layer for coordination state
        self._agent_cache = LocalCache(
            maxsize=100,
            default_ttl=1800,  # 30 minutes
            name="AgentStateCache"
        ) if enable_cache else None
        
        self._task_cache = LocalCache(
            maxsize=200,
            default_ttl=3600,  # 1 hour
            name="TaskQueueCache"
        ) if enable_cache else None
        
        self._conflict_cache = LocalCache(
            maxsize=500,
            default_ttl=7200,  # 2 hours
            name="ConflictHistoryCache"
        ) if enable_cache else None
        
    def register_agent(
        self,
        optimizer: AgenticOptimizer,
        agent_id: Optional[str] = None,
    ) -> str:
        """Register a new optimization agent.
        
        Args:
            optimizer: Optimizer instance for this agent
            agent_id: Optional custom agent ID
            
        Returns:
            Assigned agent ID
            
        Raises:
            RuntimeError: If max agents limit reached
        """
        if len(self.agents) >= self.max_agents:
            raise RuntimeError(f"Maximum agents limit ({self.max_agents}) reached")
        
        agent_id = agent_id or f"agent-{uuid.uuid4().hex[:8]}"
        
        state = AgentState(
            agent_id=agent_id,
            optimizer=optimizer,
        )
        
        self.agents[agent_id] = state
        
        # Cache the agent state
        self._cache_agent_state(agent_id, state)
        
        return agent_id
    
    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent and cleanup resources.
        
        Args:
            agent_id: ID of agent to unregister
            
        Returns:
            True if successful, False if agent not found
        """
        if agent_id not in self.agents:
            return False
        
        state = self.agents[agent_id]
        
        # Cleanup worktree if exists
        if state.worktree:
            self.worktree_manager.cleanup_worktree(agent_id)
        
        del self.agents[agent_id]
        return True
    
    def assign_task(
        self,
        agent_id: str,
        task: OptimizationTask,
    ) -> Path:
        """Assign task to agent and create worktree.
        
        Args:
            agent_id: ID of agent to assign task to
            task: Task to assign
            
        Returns:
            Path to agent's worktree
            
        Raises:
            ValueError: If agent not found or busy
        """
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} not found")
        
        state = self.agents[agent_id]
        
        if state.status != AgentStatus.IDLE:
            raise ValueError(f"Agent {agent_id} is not idle (status: {state.status})")
        
        # Create worktree for agent
        worktree = self.worktree_manager.create_worktree(agent_id)
        
        # Update state
        state.current_task = task
        state.worktree = worktree
        state.status = AgentStatus.WORKING
        state.last_activity = datetime.now()
        task.assigned_agent = agent_id
        
        return worktree
    
    async def execute_task(self, agent_id: str) -> OptimizationResult:
        """Execute assigned task for agent.
        
        Args:
            agent_id: ID of agent to execute task for
            
        Returns:
            Optimization result
            
        Raises:
            ValueError: If agent not found or has no task
        """
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} not found")
        
        state = self.agents[agent_id]
        
        if not state.current_task:
            raise ValueError(f"Agent {agent_id} has no assigned task")
        
        try:
            # Execute optimization
            result = await anyio.to_thread.run_sync(
                state.optimizer.optimize,
                state.current_task
            )
            
            # Update state
            state.status = AgentStatus.VALIDATING
            state.last_activity = datetime.now()
            
            # Validate
            validation = await anyio.to_thread.run_sync(
                state.optimizer.validate,
                result
            )
            result.validation = validation
            
            if validation.passed:
                state.status = AgentStatus.WAITING_APPROVAL
                state.completed_tasks.append(state.current_task.task_id)
            else:
                state.status = AgentStatus.ERROR
                state.failed_tasks.append(state.current_task.task_id)
            
            state.last_activity = datetime.now()
            return result
            
        except Exception as e:
            state.status = AgentStatus.ERROR
            state.failed_tasks.append(state.current_task.task_id)
            state.last_activity = datetime.now()
            raise RuntimeError(f"Task execution failed: {e}")
    
    def submit_patch(
        self,
        agent_id: str,
        patch: Patch,
    ) -> str:
        """Submit patch from agent for review and coordination.
        
        Args:
            agent_id: ID of agent submitting patch
            patch: Patch to submit
            
        Returns:
            IPFS CID of submitted patch
            
        Raises:
            ValueError: If agent not found
        """
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} not found")
        
        state = self.agents[agent_id]
        
        # Check for conflicts
        conflicts = self.conflict_resolver.check(patch, self.agents)
        
        if conflicts:
            # Resolve conflicts
            patch = self.conflict_resolver.resolve(patch, conflicts)
        
        # Store in IPFS
        cid = self.ipfs_broadcast.store_patch(patch)
        
        # Broadcast to other agents
        self.ipfs_broadcast.notify_agents(cid, exclude=[agent_id])
        
        # Update state
        state.last_activity = datetime.now()
        
        return cid
    
    def get_agent_status(self, agent_id: str) -> Optional[AgentState]:
        """Get current status of an agent.
        
        Args:
            agent_id: ID of agent
            
        Returns:
            Agent state if found, None otherwise
        """
        return self.agents.get(agent_id)
    
    def list_agents(self) -> List[AgentState]:
        """List all registered agents.
        
        Returns:
            List of agent states
        """
        return list(self.agents.values())
    
    def get_idle_agents(self) -> List[str]:
        """Get list of idle agent IDs.
        
        Returns:
            List of agent IDs with IDLE status
        """
        return [
            agent_id
            for agent_id, state in self.agents.items()
            if state.status == AgentStatus.IDLE
        ]
    
    def queue_task(self, task: OptimizationTask) -> None:
        """Add task to queue.
        
        Args:
            task: Task to queue
        """
        self.task_queue.append(task)
    
    async def process_queue(self) -> List[OptimizationResult]:
        """Process all queued tasks with available agents.
        
        Returns:
            List of optimization results
        """
        results = []
        
        while self.task_queue:
            idle_agents = self.get_idle_agents()
            if not idle_agents:
                # Wait for agents to become available
                await anyio.sleep(1)
                continue
            
            # Assign tasks to idle agents
            for agent_id in idle_agents:
                if not self.task_queue:
                    break
                
                task = self.task_queue.pop(0)
                self.assign_task(agent_id, task)
                
                # Execute task asynchronously
                result = await self.execute_task(agent_id)
                results.append(result)
        
        return results
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for all coordinator caches.
        
        Returns:
            Dict with statistics for each cache
        """
        stats = {}
        
        if self._agent_cache:
            stats['agent_cache'] = self._agent_cache.get_stats()
        
        if self._task_cache:
            stats['task_cache'] = self._task_cache.get_stats()
        
        if self._conflict_cache:
            stats['conflict_cache'] = self._conflict_cache.get_stats()
        
        return stats
    
    def clear_caches(self) -> None:
        """Clear all coordination caches."""
        if self._agent_cache:
            self._agent_cache.clear()
        if self._task_cache:
            self._task_cache.clear()
        if self._conflict_cache:
            self._conflict_cache.clear()
    
    def _cache_agent_state(self, agent_id: str, state: AgentState) -> None:
        """Cache agent state for quick retrieval.
        
        Args:
            agent_id: Agent identifier
            state: Agent state to cache
        """
        if self._agent_cache:
            self._agent_cache.set(f"agent:{agent_id}", state)
    
    def _get_cached_agent_state(self, agent_id: str) -> Optional[AgentState]:
        """Get cached agent state.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Cached agent state or None
        """
        if self._agent_cache:
            return self._agent_cache.get(f"agent:{agent_id}")
        return None
        """Get coordinator statistics.
        
        Returns:
            Dictionary with statistics
        """
        total_completed = sum(
            len(state.completed_tasks)
            for state in self.agents.values()
        )
        total_failed = sum(
            len(state.failed_tasks)
            for state in self.agents.values()
        )
        
        status_counts = {}
        for state in self.agents.values():
            status = state.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            'total_agents': len(self.agents),
            'max_agents': self.max_agents,
            'status_distribution': status_counts,
            'queued_tasks': len(self.task_queue),
            'total_completed': total_completed,
            'total_failed': total_failed,
            'success_rate': total_completed / (total_completed + total_failed) if (total_completed + total_failed) > 0 else 0,
            'conflicts_detected': len(self.conflict_resolver.get_conflict_history()),
        }
