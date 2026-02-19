"""P2P Workflow Scheduler wrapper for MCP++ integration.

This module provides a wrapper around the MCP++ P2P workflow scheduler,
enabling distributed workflow execution across P2P networks.

Module: ipfs_datasets_py.mcp_server.mcplusplus.workflow_scheduler
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import from MCP++
try:
    from ipfs_accelerate_py.mcplusplus_module.p2p.workflow import (
        P2PWorkflowScheduler,
        get_scheduler as _get_scheduler,
        reset_scheduler as _reset_scheduler,
        HAVE_P2P_SCHEDULER,
    )

    HAVE_WORKFLOW_SCHEDULER = HAVE_P2P_SCHEDULER
except ImportError:
    HAVE_WORKFLOW_SCHEDULER = False
    P2PWorkflowScheduler = None  # type: ignore
    _get_scheduler = None  # type: ignore
    _reset_scheduler = None  # type: ignore


def create_workflow_scheduler(
    peer_id: Optional[str] = None,
    context: Optional["ServerContext"] = None,
    **kwargs: Any
) -> Optional[P2PWorkflowScheduler]:
    """Create a P2P workflow scheduler instance.

    Args:
        peer_id: Optional peer ID. If not provided, will be generated.
        context: Optional ServerContext. If provided, scheduler is managed by context.
        **kwargs: Additional configuration options

    Returns:
        P2PWorkflowScheduler instance or None if not available
        
    Note:
        If context is provided, the scheduler is stored in context.workflow_scheduler
        for lifecycle management.

    Example:
        >>> # New code (recommended):
        >>> with ServerContext() as ctx:
        ...     scheduler = create_workflow_scheduler(context=ctx)
        
        >>> # Legacy code (still works):
        >>> scheduler = create_workflow_scheduler()
    """
    if not HAVE_WORKFLOW_SCHEDULER:
        logger.warning("Workflow scheduler not available - MCP++ module not installed")
        return None

    try:
        scheduler = _get_scheduler() if _get_scheduler else None
        
        # If context provided, store scheduler for lifecycle management
        if context is not None and scheduler is not None:
            context.workflow_scheduler = scheduler
            
        return scheduler
    except Exception as e:
        logger.error(f"Failed to create workflow scheduler: {e}")
        return None


def get_scheduler(context: Optional["ServerContext"] = None) -> Optional[P2PWorkflowScheduler]:
    """Get or create the P2P workflow scheduler instance.
    
    Args:
        context: Optional ServerContext. If provided, returns context's scheduler.
                Otherwise, falls back to global instance for backward compatibility.

    Returns:
        P2PWorkflowScheduler instance or None if not available
        
    Note:
        The global instance is deprecated. New code should use ServerContext.
        
    Example:
        >>> # New code (recommended):
        >>> with ServerContext() as ctx:
        ...     scheduler = get_scheduler(ctx)
        
        >>> # Legacy code (still works):
        >>> scheduler = get_scheduler()
    """
    # If context provided, use it (new pattern)
    if context is not None:
        return context.workflow_scheduler
    
    # Fallback to global for backward compatibility (deprecated)
    if not HAVE_WORKFLOW_SCHEDULER:
        return None

    try:
        return _get_scheduler() if _get_scheduler else None
    except Exception as e:
        logger.error(f"Failed to get workflow scheduler: {e}")
        return None


def reset_scheduler() -> None:
    """Reset the global workflow scheduler instance.

    Useful for testing or when needing to reconfigure the scheduler.
    """
    if not HAVE_WORKFLOW_SCHEDULER:
        return

    try:
        if _reset_scheduler:
            _reset_scheduler()
    except Exception as e:
        logger.error(f"Failed to reset workflow scheduler: {e}")


async def submit_workflow(
    workflow_name: str,
    tasks: List[Dict[str, Any]],
    **kwargs: Any
) -> Optional[str]:
    """Submit a workflow to the P2P network.

    Args:
        workflow_name: Name of the workflow
        tasks: List of tasks to execute
        **kwargs: Additional workflow options

    Returns:
        Workflow ID if successful, None otherwise

    Example:
        >>> workflow_id = await submit_workflow(
        ...     "inference-pipeline",
        ...     [{"task": "inference", "model": "gpt2", "prompt": "Hello"}]
        ... )
    """
    scheduler = get_scheduler()
    if not scheduler:
        logger.error("Cannot submit workflow: scheduler not available")
        return None

    try:
        # The actual submit method will be called on the scheduler
        # This is a placeholder for the integration
        logger.info(f"Submitting workflow: {workflow_name} with {len(tasks)} tasks")
        # TODO: Implement actual workflow submission
        return None
    except Exception as e:
        logger.error(f"Failed to submit workflow: {e}")
        return None


__all__ = [
    "HAVE_WORKFLOW_SCHEDULER",
    "P2PWorkflowScheduler",
    "create_workflow_scheduler",
    "get_scheduler",
    "reset_scheduler",
    "submit_workflow",
]
