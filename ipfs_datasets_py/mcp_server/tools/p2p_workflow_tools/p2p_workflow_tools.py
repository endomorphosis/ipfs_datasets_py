"""
P2P Workflow Tools for MCP Server

Exposes peer-to-peer workflow scheduling functionality through MCP tools.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Import the P2P workflow scheduler
try:
    from ipfs_datasets_py.p2p_workflow_scheduler import (
        get_scheduler,
        WorkflowDefinition,
        WorkflowTag,
        MerkleClock,
        calculate_hamming_distance
    )
    P2P_SCHEDULER_AVAILABLE = True
except ImportError:
    P2P_SCHEDULER_AVAILABLE = False
    logger.warning("P2P workflow scheduler not available")


async def initialize_p2p_scheduler(
    peer_id: Optional[str] = None,
    peers: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Initialize the P2P workflow scheduler.
    
    Args:
        peer_id: Optional peer identifier (auto-generated if not provided)
        peers: Optional list of known peer IDs
        
    Returns:
        Dict with initialization status
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        scheduler = get_scheduler(peer_id=peer_id, peers=peers)
        status = scheduler.get_status()
        
        return {
            'success': True,
            'message': 'P2P workflow scheduler initialized',
            'status': status
        }
    except Exception as e:
        logger.error(f"Failed to initialize P2P scheduler: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def schedule_p2p_workflow(
    workflow_id: str,
    name: str,
    tags: List[str],
    priority: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Schedule a workflow for P2P execution.
    
    Args:
        workflow_id: Unique workflow identifier
        name: Workflow name
        tags: List of workflow tags (e.g., 'p2p_eligible', 'code_gen', 'web_scrape')
        priority: Priority value (lower = higher priority)
        metadata: Optional metadata dictionary
        
    Returns:
        Dict with scheduling result
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        # Parse tags
        workflow_tags = []
        for tag in tags:
            try:
                workflow_tags.append(WorkflowTag(tag))
            except ValueError:
                logger.warning(f"Unknown workflow tag: {tag}")
        
        # Create workflow definition
        workflow = WorkflowDefinition(
            workflow_id=workflow_id,
            name=name,
            tags=workflow_tags,
            priority=priority,
            metadata=metadata or {}
        )
        
        # Schedule workflow
        scheduler = get_scheduler()
        result = scheduler.schedule_workflow(workflow)
        
        return {
            'success': result['success'],
            'workflow_id': workflow_id,
            'result': result,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to schedule workflow: {e}")
        return {
            'success': False,
            'error': str(e),
            'workflow_id': workflow_id
        }


async def get_next_p2p_workflow() -> Dict[str, Any]:
    """
    Get the next workflow from the priority queue.
    
    Returns:
        Dict with next workflow or empty if queue is empty
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        scheduler = get_scheduler()
        workflow = scheduler.get_next_workflow()
        
        if workflow is None:
            return {
                'success': True,
                'message': 'No workflows in queue',
                'workflow': None
            }
        
        return {
            'success': True,
            'workflow': workflow.to_dict(),
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get next workflow: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def add_p2p_peer(
    peer_id: str
) -> Dict[str, Any]:
    """
    Add a peer to the P2P network.
    
    Args:
        peer_id: Peer identifier to add
        
    Returns:
        Dict with operation status
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        scheduler = get_scheduler()
        scheduler.add_peer(peer_id)
        
        return {
            'success': True,
            'message': f'Added peer {peer_id}',
            'num_peers': len(scheduler.peers),
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to add peer: {e}")
        return {
            'success': False,
            'error': str(e),
            'peer_id': peer_id
        }


async def remove_p2p_peer(
    peer_id: str
) -> Dict[str, Any]:
    """
    Remove a peer from the P2P network.
    
    Args:
        peer_id: Peer identifier to remove
        
    Returns:
        Dict with operation status
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        scheduler = get_scheduler()
        scheduler.remove_peer(peer_id)
        
        return {
            'success': True,
            'message': f'Removed peer {peer_id}',
            'num_peers': len(scheduler.peers),
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to remove peer: {e}")
        return {
            'success': False,
            'error': str(e),
            'peer_id': peer_id
        }


async def get_p2p_scheduler_status() -> Dict[str, Any]:
    """
    Get P2P scheduler status.
    
    Returns:
        Dict with scheduler status
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        scheduler = get_scheduler()
        status = scheduler.get_status()
        
        return {
            'success': True,
            'status': status,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get scheduler status: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def calculate_peer_distance(
    hash1: str,
    hash2: str
) -> Dict[str, Any]:
    """
    Calculate hamming distance between two hashes.
    
    Args:
        hash1: First hash (hex string)
        hash2: Second hash (hex string)
        
    Returns:
        Dict with hamming distance
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        distance = calculate_hamming_distance(hash1, hash2)
        
        return {
            'success': True,
            'distance': distance,
            'hash1': hash1,
            'hash2': hash2,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to calculate hamming distance: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def get_workflow_tags() -> Dict[str, Any]:
    """
    Get available workflow tags.
    
    Returns:
        Dict with list of workflow tags
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        tags = [tag.value for tag in WorkflowTag]
        tag_descriptions = {
            'github_api': 'Use GitHub API (default)',
            'p2p_eligible': 'Can be executed via P2P',
            'p2p_only': 'Must be executed via P2P (bypass GitHub completely)',
            'unit_test': 'Unit test workflow (GitHub API)',
            'code_gen': 'Code generation workflow (P2P eligible)',
            'web_scrape': 'Web scraping workflow (P2P eligible)',
            'data_processing': 'Data processing workflow (P2P eligible)'
        }
        
        return {
            'success': True,
            'tags': tags,
            'descriptions': tag_descriptions,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get workflow tags: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def merge_merkle_clock(
    other_peer_id: str,
    other_counter: int,
    other_parent_hash: Optional[str] = None,
    other_timestamp: Optional[float] = None
) -> Dict[str, Any]:
    """
    Merge another peer's merkle clock into ours.
    
    Args:
        other_peer_id: Other peer's ID
        other_counter: Other peer's clock counter
        other_parent_hash: Other peer's parent hash
        other_timestamp: Other peer's timestamp
        
    Returns:
        Dict with merge result
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        # Create merkle clock from other peer's data
        other_clock = MerkleClock(
            peer_id=other_peer_id,
            counter=other_counter,
            parent_hash=other_parent_hash,
            timestamp=other_timestamp or datetime.now().timestamp()
        )
        
        # Merge clocks
        scheduler = get_scheduler()
        scheduler.merge_clock(other_clock)
        
        return {
            'success': True,
            'message': f'Merged clock from peer {other_peer_id}',
            'new_clock': scheduler.clock.to_dict(),
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to merge merkle clock: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def get_assigned_workflows() -> Dict[str, Any]:
    """
    Get list of workflows assigned to this peer.
    
    Returns:
        Dict with list of assigned workflow IDs
    """
    if not P2P_SCHEDULER_AVAILABLE:
        return {
            'success': False,
            'error': 'P2P workflow scheduler not available'
        }
    
    try:
        scheduler = get_scheduler()
        assigned = scheduler.get_assigned_workflows()
        
        return {
            'success': True,
            'assigned_workflows': assigned,
            'count': len(assigned),
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get assigned workflows: {e}")
        return {
            'success': False,
            'error': str(e)
        }
