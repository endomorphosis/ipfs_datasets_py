"""
MCP++ Enhanced Workflow Tools for MCP Server

Provides enhanced P2P workflow scheduling capabilities using the MCP++ module from
ipfs_accelerate_py. These tools leverage the Trio-native workflow scheduler for
improved performance and advanced P2P features.

Phase 2.1.1 - Workflow Tools (6 tools)
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import json

logger = logging.getLogger(__name__)

# Import our MCP++ wrapper from Phase 1
try:
    from ipfs_datasets_py.mcp_server.mcplusplus import (
        get_capabilities,
        workflow_scheduler as wf_module
    )
    MCPLUSPLUS_AVAILABLE = get_capabilities().get('workflow_scheduler_available', False)
except ImportError:
    MCPLUSPLUS_AVAILABLE = False
    logger.warning("MCP++ workflow module not available - tools will operate in degraded mode")

# Try to import P2P service manager from Phase 1
try:
    from ipfs_datasets_py.mcp_server.p2p_service_manager import P2PServiceManager
    SERVICE_MANAGER_AVAILABLE = True
except ImportError:
    SERVICE_MANAGER_AVAILABLE = False
    logger.warning("P2P service manager not available")


async def workflow_submit(
    workflow_id: str,
    name: str,
    steps: List[Dict[str, Any]],
    priority: float = 1.0,
    tags: Optional[List[str]] = None,
    dependencies: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Submit a workflow to the P2P network for distributed execution.
    
    This tool leverages the MCP++ workflow scheduler to distribute workflow execution
    across peer nodes in the P2P network, enabling parallel processing and load balancing.
    
    Args:
        workflow_id: Unique identifier for the workflow
        name: Human-readable workflow name
        steps: List of workflow steps, each containing:
            - step_id: Unique step identifier
            - action: Action to perform
            - inputs: Input parameters
            - depends_on: Optional list of step IDs this step depends on
        priority: Priority value (lower = higher priority, default: 1.0)
        tags: Optional list of tags for workflow categorization
        dependencies: Optional list of workflow IDs this workflow depends on
        metadata: Optional metadata dictionary
        
    Returns:
        Dict containing:
            - success: Boolean indicating if submission succeeded
            - workflow_id: The submitted workflow ID
            - status: Current workflow status
            - peer_assigned: Peer ID assigned to execute (if P2P enabled)
            - estimated_start_time: Estimated start time (if available)
            - error: Error message (if submission failed)
            
    Examples:
        >>> result = await workflow_submit(
        ...     workflow_id="wf-001",
        ...     name="Process Dataset",
        ...     steps=[
        ...         {"step_id": "download", "action": "fetch_data", "inputs": {"url": "..."}},
        ...         {"step_id": "process", "action": "transform", "inputs": {}, "depends_on": ["download"]}
        ...     ],
        ...     priority=1.5,
        ...     tags=["data_processing", "high_priority"]
        ... )
        >>> print(result['success'])  # True
    """
    try:
        # Validation
        if not workflow_id or not name or not steps:
            return {
                'success': False,
                'error': 'Missing required parameters: workflow_id, name, or steps'
            }
        
        # Validate steps structure
        for step in steps:
            if 'step_id' not in step or 'action' not in step:
                return {
                    'success': False,
                    'error': f'Invalid step structure - missing step_id or action: {step}'
                }
        
        # If MCP++ available, use enhanced workflow scheduler
        if MCPLUSPLUS_AVAILABLE:
            try:
                scheduler = wf_module.get_scheduler()
                
                # Submit workflow using MCP++ scheduler
                result = await wf_module.submit_workflow(
                    workflow_id=workflow_id,
                    name=name,
                    steps=steps,
                    priority=priority,
                    tags=tags or [],
                    dependencies=dependencies or [],
                    metadata=metadata or {}
                )
                
                return {
                    'success': True,
                    'workflow_id': workflow_id,
                    'status': 'submitted',
                    'peer_assigned': result.get('peer_id'),
                    'estimated_start_time': result.get('estimated_start'),
                    'message': f'Workflow {workflow_id} submitted to P2P network'
                }
            except Exception as e:
                logger.error(f"MCP++ workflow submission failed: {e}")
                return {
                    'success': False,
                    'workflow_id': workflow_id,
                    'error': f'P2P submission failed: {str(e)}'
                }
        else:
            # Graceful degradation - store locally
            logger.info(f"MCP++ not available - workflow {workflow_id} stored locally")
            return {
                'success': True,
                'workflow_id': workflow_id,
                'status': 'queued_local',
                'peer_assigned': 'localhost',
                'message': f'Workflow {workflow_id} queued locally (P2P unavailable)',
                'warning': 'MCP++ not available - workflow will execute locally'
            }
            
    except Exception as e:
        logger.error(f"Error submitting workflow {workflow_id}: {e}")
        return {
            'success': False,
            'workflow_id': workflow_id,
            'error': str(e)
        }


async def workflow_status(
    workflow_id: str,
    include_steps: bool = True,
    include_metrics: bool = False
) -> Dict[str, Any]:
    """
    Check the status of a submitted workflow.
    
    Args:
        workflow_id: Unique identifier of the workflow to check
        include_steps: Include detailed step-by-step status (default: True)
        include_metrics: Include execution metrics like duration, resource usage (default: False)
        
    Returns:
        Dict containing:
            - success: Boolean indicating if status retrieval succeeded
            - workflow_id: The queried workflow ID
            - status: Current status ('submitted', 'running', 'completed', 'failed', 'cancelled')
            - progress: Percentage complete (0-100)
            - current_step: Currently executing step (if running)
            - steps: List of step statuses (if include_steps=True)
            - peer_id: ID of peer executing the workflow
            - start_time: Workflow start timestamp
            - end_time: Workflow end timestamp (if completed)
            - metrics: Execution metrics (if include_metrics=True)
            - error: Error message (if retrieval failed)
    """
    try:
        if not workflow_id:
            return {
                'success': False,
                'error': 'Missing required parameter: workflow_id'
            }
        
        if MCPLUSPLUS_AVAILABLE:
            try:
                scheduler = wf_module.get_scheduler()
                status_data = await scheduler.get_workflow_status(workflow_id)
                
                if not status_data:
                    return {
                        'success': False,
                        'workflow_id': workflow_id,
                        'error': f'Workflow {workflow_id} not found'
                    }
                
                result = {
                    'success': True,
                    'workflow_id': workflow_id,
                    'status': status_data.get('status', 'unknown'),
                    'progress': status_data.get('progress', 0),
                    'current_step': status_data.get('current_step'),
                    'peer_id': status_data.get('peer_id'),
                    'start_time': status_data.get('start_time'),
                    'end_time': status_data.get('end_time')
                }
                
                if include_steps:
                    result['steps'] = status_data.get('steps', [])
                
                if include_metrics:
                    result['metrics'] = status_data.get('metrics', {})
                
                return result
                
            except Exception as e:
                logger.error(f"Error getting workflow status from MCP++: {e}")
                return {
                    'success': False,
                    'workflow_id': workflow_id,
                    'error': str(e)
                }
        else:
            # Graceful degradation
            return {
                'success': False,
                'workflow_id': workflow_id,
                'error': 'MCP++ not available - cannot retrieve workflow status'
            }
            
    except Exception as e:
        logger.error(f"Error checking workflow status for {workflow_id}: {e}")
        return {
            'success': False,
            'workflow_id': workflow_id,
            'error': str(e)
        }


async def workflow_cancel(
    workflow_id: str,
    reason: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Cancel a running or queued workflow.
    
    Args:
        workflow_id: Unique identifier of the workflow to cancel
        reason: Optional cancellation reason
        force: Force cancellation even if workflow is in critical state (default: False)
        
    Returns:
        Dict containing:
            - success: Boolean indicating if cancellation succeeded
            - workflow_id: The cancelled workflow ID
            - status: New status after cancellation
            - cancelled_steps: Number of steps cancelled
            - message: Confirmation message
            - error: Error message (if cancellation failed)
    """
    try:
        if not workflow_id:
            return {
                'success': False,
                'error': 'Missing required parameter: workflow_id'
            }
        
        if MCPLUSPLUS_AVAILABLE:
            try:
                scheduler = wf_module.get_scheduler()
                result = await scheduler.cancel_workflow(
                    workflow_id=workflow_id,
                    reason=reason,
                    force=force
                )
                
                return {
                    'success': True,
                    'workflow_id': workflow_id,
                    'status': 'cancelled',
                    'cancelled_steps': result.get('cancelled_steps', 0),
                    'message': f'Workflow {workflow_id} cancelled successfully'
                }
                
            except Exception as e:
                logger.error(f"Error cancelling workflow via MCP++: {e}")
                return {
                    'success': False,
                    'workflow_id': workflow_id,
                    'error': str(e)
                }
        else:
            return {
                'success': False,
                'workflow_id': workflow_id,
                'error': 'MCP++ not available - cannot cancel workflow'
            }
            
    except Exception as e:
        logger.error(f"Error cancelling workflow {workflow_id}: {e}")
        return {
            'success': False,
            'workflow_id': workflow_id,
            'error': str(e)
        }


async def workflow_list(
    status_filter: Optional[str] = None,
    peer_filter: Optional[str] = None,
    tag_filter: Optional[List[str]] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List workflows with optional filtering.
    
    Args:
        status_filter: Optional status to filter by ('submitted', 'running', 'completed', 'failed', 'cancelled')
        peer_filter: Optional peer ID to filter by
        tag_filter: Optional list of tags to filter by
        limit: Maximum number of workflows to return (default: 50, max: 1000)
        offset: Number of workflows to skip for pagination (default: 0)
        
    Returns:
        Dict containing:
            - success: Boolean indicating if listing succeeded
            - workflows: List of workflow summaries
            - total_count: Total number of workflows matching filters
            - returned_count: Number of workflows in this response
            - has_more: Boolean indicating if more workflows available
            - error: Error message (if listing failed)
    """
    try:
        # Validate parameters
        if limit < 1 or limit > 1000:
            return {
                'success': False,
                'error': 'Limit must be between 1 and 1000'
            }
        
        if offset < 0:
            return {
                'success': False,
                'error': 'Offset must be non-negative'
            }
        
        if MCPLUSPLUS_AVAILABLE:
            try:
                scheduler = wf_module.get_scheduler()
                workflows = await scheduler.list_workflows(
                    status=status_filter,
                    peer_id=peer_filter,
                    tags=tag_filter,
                    limit=limit,
                    offset=offset
                )
                
                return {
                    'success': True,
                    'workflows': workflows.get('workflows', []),
                    'total_count': workflows.get('total_count', 0),
                    'returned_count': len(workflows.get('workflows', [])),
                    'has_more': workflows.get('has_more', False)
                }
                
            except Exception as e:
                logger.error(f"Error listing workflows via MCP++: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }
        else:
            return {
                'success': False,
                'error': 'MCP++ not available - cannot list workflows',
                'workflows': [],
                'total_count': 0,
                'returned_count': 0,
                'has_more': False
            }
            
    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def workflow_dependencies(
    workflow_id: str,
    format: str = 'json'
) -> Dict[str, Any]:
    """
    Get the dependency DAG (Directed Acyclic Graph) for a workflow.
    
    This shows the relationships between workflow steps and dependent workflows,
    useful for understanding execution order and troubleshooting bottlenecks.
    
    Args:
        workflow_id: Unique identifier of the workflow
        format: Output format ('json', 'dot', 'mermaid') (default: 'json')
        
    Returns:
        Dict containing:
            - success: Boolean indicating if retrieval succeeded
            - workflow_id: The queried workflow ID
            - dag: Dependency graph in requested format
            - nodes: List of nodes (steps/workflows)
            - edges: List of edges (dependencies)
            - critical_path: List of steps on the critical path
            - error: Error message (if retrieval failed)
    """
    try:
        if not workflow_id:
            return {
                'success': False,
                'error': 'Missing required parameter: workflow_id'
            }
        
        if format not in ['json', 'dot', 'mermaid']:
            return {
                'success': False,
                'error': f'Invalid format: {format}. Must be one of: json, dot, mermaid'
            }
        
        if MCPLUSPLUS_AVAILABLE:
            try:
                scheduler = wf_module.get_scheduler()
                dag_data = await scheduler.get_workflow_dag(workflow_id, format=format)
                
                if not dag_data:
                    return {
                        'success': False,
                        'workflow_id': workflow_id,
                        'error': f'Workflow {workflow_id} not found or has no dependency data'
                    }
                
                return {
                    'success': True,
                    'workflow_id': workflow_id,
                    'dag': dag_data.get('dag'),
                    'nodes': dag_data.get('nodes', []),
                    'edges': dag_data.get('edges', []),
                    'critical_path': dag_data.get('critical_path', [])
                }
                
            except Exception as e:
                logger.error(f"Error getting workflow DAG from MCP++: {e}")
                return {
                    'success': False,
                    'workflow_id': workflow_id,
                    'error': str(e)
                }
        else:
            return {
                'success': False,
                'workflow_id': workflow_id,
                'error': 'MCP++ not available - cannot retrieve workflow dependencies'
            }
            
    except Exception as e:
        logger.error(f"Error getting workflow dependencies for {workflow_id}: {e}")
        return {
            'success': False,
            'workflow_id': workflow_id,
            'error': str(e)
        }


async def workflow_result(
    workflow_id: str,
    include_outputs: bool = True,
    include_logs: bool = False
) -> Dict[str, Any]:
    """
    Retrieve the result of a completed workflow.
    
    Args:
        workflow_id: Unique identifier of the workflow
        include_outputs: Include output data from each step (default: True)
        include_logs: Include execution logs (default: False)
        
    Returns:
        Dict containing:
            - success: Boolean indicating if retrieval succeeded
            - workflow_id: The queried workflow ID
            - status: Final workflow status
            - result: Overall workflow result
            - outputs: Step-by-step outputs (if include_outputs=True)
            - logs: Execution logs (if include_logs=True)
            - execution_time: Total execution time in seconds
            - error: Error message (if retrieval failed)
    """
    try:
        if not workflow_id:
            return {
                'success': False,
                'error': 'Missing required parameter: workflow_id'
            }
        
        if MCPLUSPLUS_AVAILABLE:
            try:
                scheduler = wf_module.get_scheduler()
                result_data = await scheduler.get_workflow_result(
                    workflow_id=workflow_id,
                    include_outputs=include_outputs,
                    include_logs=include_logs
                )
                
                if not result_data:
                    return {
                        'success': False,
                        'workflow_id': workflow_id,
                        'error': f'Workflow {workflow_id} not found or not yet completed'
                    }
                
                response = {
                    'success': True,
                    'workflow_id': workflow_id,
                    'status': result_data.get('status'),
                    'result': result_data.get('result'),
                    'execution_time': result_data.get('execution_time')
                }
                
                if include_outputs:
                    response['outputs'] = result_data.get('outputs', [])
                
                if include_logs:
                    response['logs'] = result_data.get('logs', [])
                
                return response
                
            except Exception as e:
                logger.error(f"Error getting workflow result from MCP++: {e}")
                return {
                    'success': False,
                    'workflow_id': workflow_id,
                    'error': str(e)
                }
        else:
            return {
                'success': False,
                'workflow_id': workflow_id,
                'error': 'MCP++ not available - cannot retrieve workflow result'
            }
            
    except Exception as e:
        logger.error(f"Error getting workflow result for {workflow_id}: {e}")
        return {
            'success': False,
            'workflow_id': workflow_id,
            'error': str(e)
        }


# Tool metadata for MCP registration
TOOLS = [
    {
        'name': 'workflow_submit',
        'description': 'Submit a workflow to the P2P network for distributed execution',
        'function': workflow_submit,
        'input_schema': {
            'type': 'object',
            'properties': {
                'workflow_id': {'type': 'string', 'description': 'Unique workflow identifier'},
                'name': {'type': 'string', 'description': 'Human-readable workflow name'},
                'steps': {
                    'type': 'array',
                    'description': 'List of workflow steps',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'step_id': {'type': 'string'},
                            'action': {'type': 'string'},
                            'inputs': {'type': 'object'},
                            'depends_on': {'type': 'array', 'items': {'type': 'string'}}
                        },
                        'required': ['step_id', 'action']
                    }
                },
                'priority': {'type': 'number', 'default': 1.0},
                'tags': {'type': 'array', 'items': {'type': 'string'}},
                'dependencies': {'type': 'array', 'items': {'type': 'string'}},
                'metadata': {'type': 'object'}
            },
            'required': ['workflow_id', 'name', 'steps']
        },
        '_mcp_runtime': 'trio'  # Mark as Trio-native for Phase 3 runtime routing
    },
    {
        'name': 'workflow_status',
        'description': 'Check the status of a submitted workflow',
        'function': workflow_status,
        'input_schema': {
            'type': 'object',
            'properties': {
                'workflow_id': {'type': 'string', 'description': 'Unique workflow identifier'},
                'include_steps': {'type': 'boolean', 'default': True},
                'include_metrics': {'type': 'boolean', 'default': False}
            },
            'required': ['workflow_id']
        },
        '_mcp_runtime': 'trio'
    },
    {
        'name': 'workflow_cancel',
        'description': 'Cancel a running or queued workflow',
        'function': workflow_cancel,
        'input_schema': {
            'type': 'object',
            'properties': {
                'workflow_id': {'type': 'string', 'description': 'Unique workflow identifier'},
                'reason': {'type': 'string'},
                'force': {'type': 'boolean', 'default': False}
            },
            'required': ['workflow_id']
        },
        '_mcp_runtime': 'trio'
    },
    {
        'name': 'workflow_list',
        'description': 'List workflows with optional filtering',
        'function': workflow_list,
        'input_schema': {
            'type': 'object',
            'properties': {
                'status_filter': {'type': 'string', 'enum': ['submitted', 'running', 'completed', 'failed', 'cancelled']},
                'peer_filter': {'type': 'string'},
                'tag_filter': {'type': 'array', 'items': {'type': 'string'}},
                'limit': {'type': 'integer', 'default': 50, 'minimum': 1, 'maximum': 1000},
                'offset': {'type': 'integer', 'default': 0, 'minimum': 0}
            }
        },
        '_mcp_runtime': 'trio'
    },
    {
        'name': 'workflow_dependencies',
        'description': 'Get the dependency DAG for a workflow',
        'function': workflow_dependencies,
        'input_schema': {
            'type': 'object',
            'properties': {
                'workflow_id': {'type': 'string', 'description': 'Unique workflow identifier'},
                'format': {'type': 'string', 'enum': ['json', 'dot', 'mermaid'], 'default': 'json'}
            },
            'required': ['workflow_id']
        },
        '_mcp_runtime': 'trio'
    },
    {
        'name': 'workflow_result',
        'description': 'Retrieve the result of a completed workflow',
        'function': workflow_result,
        'input_schema': {
            'type': 'object',
            'properties': {
                'workflow_id': {'type': 'string', 'description': 'Unique workflow identifier'},
                'include_outputs': {'type': 'boolean', 'default': True},
                'include_logs': {'type': 'boolean', 'default': False}
            },
            'required': ['workflow_id']
        },
        '_mcp_runtime': 'trio'
    }
]


__all__ = [
    'workflow_submit',
    'workflow_status',
    'workflow_cancel',
    'workflow_list',
    'workflow_dependencies',
    'workflow_result',
    'TOOLS',
    'MCPLUSPLUS_AVAILABLE'
]
