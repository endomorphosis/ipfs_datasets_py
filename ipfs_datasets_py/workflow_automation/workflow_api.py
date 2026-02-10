"""Workflow automation and pipeline management core API.

This module contains the *core* implementation used by MCP workflow tool wrappers.
It is intentionally MCP-agnostic so it can be imported by CLI and other code.
"""

import logging
import anyio
import uuid
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

# Import the P2P workflow scheduler
try:
    from ipfs_datasets_py.p2p_networking.p2p_workflow_scheduler import (
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

# Workflow state tracking
WORKFLOW_REGISTRY = {}
EXECUTION_HISTORY = {}
TEMPLATE_REGISTRY = {}


async def execute_workflow(
    workflow_definition: Optional[Dict[str, Any]] = None,
    workflow_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    workflow: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    async_execution: Optional[bool] = None,
    action: Optional[str] = None,
    template_spec: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute a multi-step workflow with conditional logic and error handling.
    
    Args:
        workflow_definition: Dictionary defining workflow steps and logic
        workflow_id: Optional workflow ID (generated if not provided)
        context: Additional context data for workflow execution
        workflow: Legacy alias for `workflow_definition`.
        params: Legacy alias for `context`.
        async_execution: Legacy flag for async execution (ignored; function is async).
        action: Legacy action shortcut (pause/resume).
        template_spec: Legacy alias for template definition when using template actions.
        
    Returns:
        Dict containing workflow execution results
    """
    try:
        if action == "create_template":
            return await create_template(template_spec or workflow_definition or {})

        if action == "list_templates":
            return await list_templates()

        if action in {"pause", "resume"}:
            if not workflow_id:
                workflow_id = f"workflow_{uuid.uuid4().hex[:8]}"

            workflow_info = WORKFLOW_REGISTRY.get(workflow_id, {})
            workflow_info.setdefault("definition", workflow_definition or {})
            workflow_info.setdefault("context", {})
            workflow_info["status"] = "paused" if action == "pause" else "running"
            workflow_info["updated_at"] = datetime.now().isoformat()
            WORKFLOW_REGISTRY[workflow_id] = workflow_info

            return {
                "success": True,
                "status": workflow_info["status"],
                "workflow_id": workflow_id,
                "timestamp": datetime.now().isoformat()
            }

        if workflow_definition is None and workflow:
            workflow_definition = workflow

        if workflow_definition is None:
            return {
                "success": False,
                "status": "failed",
                "workflow_id": workflow_id,
                "error": "Workflow definition is required",
                "timestamp": datetime.now().isoformat()
            }

        # Generate workflow ID if not provided
        if not workflow_id:
            workflow_id = f"workflow_{uuid.uuid4().hex[:8]}"
            
        # Initialize workflow tracking
        start_time = datetime.now()
        workflow_context = {**(context or {}), **(params or {})}

        WORKFLOW_REGISTRY[workflow_id] = {
            "definition": workflow_definition,
            "status": "running",
            "start_time": start_time.isoformat(),
            "context": workflow_context
        }
        
        # Extract workflow steps
        steps = workflow_definition.get("steps", [])
        if not steps:
            return {
                "success": False,
                "status": "failed",
                "workflow_id": workflow_id,
                "error": "No steps defined in workflow",
                "timestamp": datetime.now().isoformat()
            }
            
        # Execute workflow steps
        step_results = {}
        
        for i, step in enumerate(steps):
            step_id = step.get("id", f"step_{i}")
            step_type = step.get("type") or step.get("action", "unknown")
            step_params = step.get("parameters") or step.get("params")
            if step_params is None:
                step_params = {
                    key: value
                    for key, value in step.items()
                    if key not in {"id", "type", "action", "parameters", "params"}
                }
            
            logger.info(f"Executing workflow {workflow_id}, step {step_id}: {step_type}")
            
            try:
                # Execute step based on type
                if step_type == "embedding_generation":
                    result = await _execute_embedding_step(step_params, workflow_context)
                elif step_type == "dataset_processing":
                    result = await _execute_dataset_step(step_params, workflow_context)
                elif step_type == "vector_indexing":
                    result = await _execute_vector_step(step_params, workflow_context)
                elif step_type == "ipfs_operation":
                    result = await _execute_ipfs_step(step_params, workflow_context)
                elif step_type == "conditional":
                    result = await _execute_conditional_step(step_params, workflow_context, step_results)
                elif step_type == "parallel":
                    result = await _execute_parallel_step(step_params, workflow_context)
                else:
                    result = await _execute_generic_step(step_type, step_params, workflow_context)
                    
                step_results[step_id] = result
                
                # Update workflow context with step results
                if result.get("success") and result.get("context_updates"):
                    workflow_context.update(result["context_updates"])
                    
                # Check for early termination conditions
                if not result.get("success") and step.get("critical", False):
                    raise Exception(f"Critical step {step_id} failed: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                step_results[step_id] = {
                    "success": False,
                    "error": str(e),
                    "step_type": step_type
                }
                
                if step.get("critical", False):
                    # Update workflow status and return failure
                    WORKFLOW_REGISTRY[workflow_id]["status"] = "failed"
                    WORKFLOW_REGISTRY[workflow_id]["end_time"] = datetime.now().isoformat()
                    
                    return {
                        "success": False,
                        "status": "failed",
                        "workflow_id": workflow_id,
                        "error": f"Workflow failed at critical step {step_id}: {str(e)}",
                        "step_results": step_results,
                        "steps": step_results,
                        "execution_time": (datetime.now() - start_time).total_seconds(),
                        "timestamp": datetime.now().isoformat()
                    }
                    
        # Mark workflow as completed
        end_time = datetime.now()
        WORKFLOW_REGISTRY[workflow_id]["status"] = "completed"
        WORKFLOW_REGISTRY[workflow_id]["end_time"] = end_time.isoformat()
        
        # Calculate execution statistics
        execution_time = (end_time - start_time).total_seconds()
        success_count = sum(1 for r in step_results.values() if r.get("success"))
        total_steps = len(step_results)
        
        return {
            "success": True,
            "status": "completed",
            "workflow_id": workflow_id,
            "step_results": step_results,
            "steps": step_results,
            "execution_stats": {
                "total_steps": total_steps,
                "successful_steps": success_count,
                "failed_steps": total_steps - success_count,
                "execution_time_seconds": execution_time
            },
            "final_context": workflow_context,
            "timestamp": end_time.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        if workflow_id in WORKFLOW_REGISTRY:
            WORKFLOW_REGISTRY[workflow_id]["status"] = "failed"
            WORKFLOW_REGISTRY[workflow_id]["end_time"] = datetime.now().isoformat()
            
        return {
            "success": False,
            "status": "failed",
            "workflow_id": workflow_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def batch_process_datasets(
    datasets: List[Dict[str, Any]],
    processing_pipeline: List[str],
    batch_size: int = 10,
    parallel_workers: int = 3
) -> Dict[str, Any]:
    """
    Process multiple datasets in batches with parallel workers.
    
    Args:
        datasets: List of dataset configurations
        processing_pipeline: List of processing steps to apply
        batch_size: Number of datasets to process per batch
        parallel_workers: Number of parallel worker processes
        
    Returns:
        Dict containing batch processing results
    """
    try:
        start_time = datetime.now()
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        
        # Validate inputs
        if not datasets:
            return {
                "success": False,
                "batch_id": batch_id,
                "error": "No datasets provided for processing"
            }
            
        if not processing_pipeline:
            return {
                "success": False,
                "batch_id": batch_id,
                "error": "No processing pipeline defined"
            }
            
        # Split datasets into batches
        batches = [datasets[i:i+batch_size] for i in range(0, len(datasets), batch_size)]
        
        logger.info(f"Starting batch processing {batch_id}: {len(datasets)} datasets in {len(batches)} batches")
        
        # Process batches
        batch_results = []
        failed_datasets = []
        
        for batch_num, batch_datasets in enumerate(batches):
            logger.info(f"Processing batch {batch_num + 1}/{len(batches)}")
            
            # Create semaphore for parallel processing
            semaphore = anyio.Semaphore(parallel_workers)
            
            async def process_dataset(dataset_config):
                async with semaphore:
                    return await _process_single_dataset(dataset_config, processing_pipeline)
                    
            # Process datasets in current batch
            batch_task_results = [None] * len(batch_datasets)

            async def _run_one(idx: int, dataset_config):
                try:
                    batch_task_results[idx] = await process_dataset(dataset_config)
                except Exception as e:
                    batch_task_results[idx] = e

            async with anyio.create_task_group() as tg:
                for idx, dataset_config in enumerate(batch_datasets):
                    tg.start_soon(_run_one, idx, dataset_config)
            
            # Collect results
            for i, result in enumerate(batch_task_results):
                if isinstance(result, Exception):
                    failed_datasets.append({
                        "dataset": batch_datasets[i],
                        "error": str(result),
                        "batch": batch_num
                    })
                else:
                    batch_results.append(result)
                    
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        # Calculate statistics
        total_processed = len(batch_results)
        total_failed = len(failed_datasets)
        success_rate = (total_processed / len(datasets)) * 100 if datasets else 0
        
        return {
            "success": True,
            "batch_id": batch_id,
            "processing_stats": {
                "total_datasets": len(datasets),
                "successfully_processed": total_processed,
                "failed": total_failed,
                "success_rate_percent": round(success_rate, 2),
                "execution_time_seconds": execution_time,
                "batches_processed": len(batches),
                "parallel_workers": parallel_workers
            },
            "batch_results": batch_results[:10],  # Limit output size
            "failed_datasets": failed_datasets[:5],  # Limit output size
            "timestamp": end_time.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        return {
            "success": False,
            "batch_id": batch_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def schedule_workflow(
    workflow_definition: Optional[Dict[str, Any]] = None,
    schedule_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Schedule a workflow for future or repeated execution.
    
    Args:
        workflow_definition: Workflow configuration
        schedule_config: Scheduling configuration (time, repeat, conditions)
        
    Returns:
        Dict containing scheduling results
    """
    try:
        schedule_id = f"schedule_{uuid.uuid4().hex[:8]}"

        if schedule_config is None:
            schedule_config = workflow_definition
            workflow_definition = None

        if schedule_config is None:
            return {
                "success": False,
                "schedule_id": schedule_id,
                "error": "Schedule configuration is required",
                "timestamp": datetime.now().isoformat()
            }
        
        workflow_definition = workflow_definition or {}

        # Validate schedule configuration
        schedule_type = schedule_config.get("type") or schedule_config.get("schedule_type") or "once"
        
        if schedule_type not in ["once", "interval", "cron", "event_triggered"]:
            return {
                "success": False,
                "schedule_id": schedule_id,
                "error": f"Invalid schedule type: {schedule_type}",
                "valid_types": ["once", "interval", "cron", "event_triggered"]
            }
            
        # Mock scheduling (in production, this would integrate with a scheduler)
        scheduled_time = None
        
        if schedule_type == "once":
            scheduled_time = schedule_config.get("execute_at")
        elif schedule_type == "interval":
            interval_seconds = schedule_config.get("interval_seconds", 3600)
            scheduled_time = (datetime.now() + timedelta(seconds=interval_seconds)).isoformat()
        elif schedule_type == "cron":
            cron_expression = schedule_config.get("cron_expression", "0 0 * * *")
            scheduled_time = f"Next execution based on cron: {cron_expression}"
            
        return {
            "success": True,
            "schedule_id": schedule_id,
            "workflow_name": workflow_definition.get("name", "unnamed_workflow"),
            "schedule_type": schedule_type,
            "scheduled_time": scheduled_time,
            "status": "scheduled",
            "created_at": datetime.now().isoformat(),
            "message": f"Workflow scheduled successfully with ID {schedule_id}"
        }
        
    except Exception as e:
        logger.error(f"Workflow scheduling failed: {e}")
        return {
            "success": False,
            "schedule_id": schedule_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def create_workflow(
    workflow_id: Optional[Union[str, Dict[str, Any]]] = None,
    workflow_definition: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create or register a workflow definition."""
    if workflow_definition is None and isinstance(workflow_id, dict):
        workflow_definition = workflow_id
        workflow_id = None

    if workflow_definition is None:
        return {
            "status": "failed",
            "error": "Workflow definition is required"
        }

    if not workflow_id:
        workflow_id = workflow_definition.get("name") or f"workflow_{uuid.uuid4().hex[:8]}"

    if workflow_id in WORKFLOW_REGISTRY:
        return {
            "status": "exists",
            "workflow_id": workflow_id
        }

    WORKFLOW_REGISTRY[workflow_id] = {
        "definition": workflow_definition,
        "status": "created",
        "start_time": datetime.now().isoformat(),
        "context": {}
    }
    return {
        "status": "created",
        "workflow_id": workflow_id
    }


async def run_workflow(workflow_id: str) -> Dict[str, Any]:
    """Execute a previously registered workflow."""
    workflow_info = WORKFLOW_REGISTRY.get(workflow_id)
    if not workflow_info or not workflow_info.get("definition"):
        return {
            "status": "not_found",
            "workflow_id": workflow_id,
            "error": "Workflow not found"
        }

    result = await execute_workflow(
        workflow_definition=workflow_info.get("definition"),
        workflow_id=workflow_id
    )
    return result


async def get_workflow_status(
    workflow_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    include_details: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Get the status and results of a workflow execution.

    Args:
        workflow_id: ID of the workflow to check
        execution_id: Legacy alias for `workflow_id`.
        include_details: Legacy flag to include extra details (ignored).

    Returns:
        Dict containing workflow status and details
    """
    try:
        if not workflow_id:
            workflow_id = execution_id

        if not workflow_id:
            return {
                "success": False,
                "status": "failed",
                "workflow_id": workflow_id,
                "error": "Workflow not found",
                "available_workflows": list(WORKFLOW_REGISTRY.keys())[-5:]  # Show last 5
            }

        if workflow_id not in WORKFLOW_REGISTRY:
            return {
                "success": False,
                "status": "not_found",
                "workflow_id": workflow_id,
                "error": "Workflow not found",
                "available_workflows": list(WORKFLOW_REGISTRY.keys())[-5:]
            }
            
        workflow_info = WORKFLOW_REGISTRY[workflow_id].copy()
        
        # Calculate execution time if running
        if workflow_info["status"] == "running":
            start_time = datetime.fromisoformat(workflow_info["start_time"])
            current_time = datetime.now()
            workflow_info["running_time_seconds"] = (current_time - start_time).total_seconds()
        elif "end_time" in workflow_info:
            start_time = datetime.fromisoformat(workflow_info["start_time"])
            end_time = datetime.fromisoformat(workflow_info["end_time"])
            workflow_info["total_execution_time_seconds"] = (end_time - start_time).total_seconds()
            
        return {
            "success": True,
            "workflow_info": workflow_info,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get workflow status: {e}")
        return {
            "success": False,
            "workflow_id": workflow_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def create_template(template: Dict[str, Any]) -> Dict[str, Any]:
    """Create and store a workflow template."""
    template_id = template.get("name") or f"template_{uuid.uuid4().hex[:8]}"
    TEMPLATE_REGISTRY[template_id] = template
    return {
        "status": "created",
        "template_id": template_id,
        "template": template
    }


async def list_templates() -> Dict[str, Any]:
    """List available workflow templates."""
    templates = [
        {"template_id": template_id, **template}
        for template_id, template in TEMPLATE_REGISTRY.items()
    ]
    return {
        "status": "success",
        "templates": templates
    }


async def pause_workflow(workflow_id: str) -> Dict[str, Any]:
    """Pause a running workflow."""
    return await execute_workflow(workflow_id=workflow_id, action="pause")


async def resume_workflow(workflow_id: str) -> Dict[str, Any]:
    """Resume a paused workflow."""
    return await execute_workflow(workflow_id=workflow_id, action="resume")


async def list_workflows(include_logs: Optional[bool] = None) -> Dict[str, Any]:
    """List registered workflows with optional logs."""
    workflows = []
    for workflow_id, workflow_info in WORKFLOW_REGISTRY.items():
        entry = {
            "workflow_id": workflow_id,
            "status": workflow_info.get("status")
        }
        if include_logs:
            entry["logs"] = workflow_info.get("logs", [])
        workflows.append(entry)

    return {
        "status": "success",
        "workflows": workflows
    }


async def get_workflow_metrics(
    workflow_id: Optional[str] = None,
    include_performance: Optional[bool] = None,
    time_range: Optional[str] = None
) -> Dict[str, Any]:
    """Return basic workflow metrics summary."""
    workflow_info = WORKFLOW_REGISTRY.get(workflow_id) if workflow_id else None
    metrics = {
        "workflow_id": workflow_id,
        "status": workflow_info.get("status") if workflow_info else None,
        "time_range": time_range,
        "has_performance": bool(include_performance)
    }
    return {
        "status": "success",
        "metrics": metrics
    }


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


# Helper functions for workflow step execution

async def _execute_embedding_step(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute embedding generation step."""
    try:
        # Mock embedding generation
        text_data = params.get("text_data") or context.get("text_data", [])
        model = params.get("model", "sentence-transformers/all-MiniLM-L6-v2")
        
        # Simulate processing
        await anyio.sleep(0.1)
        
        embeddings = {
            "model": model,
            "embeddings_count": len(text_data) if isinstance(text_data, list) else 1,
            "dimension": 384,
            "processing_time": 0.1
        }
        
        return {
            "success": True,
            "result": embeddings,
            "context_updates": {"embeddings": embeddings}
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _execute_dataset_step(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute dataset processing step."""
    try:
        dataset_path = params.get("dataset_path") or context.get("dataset_path")
        operation = params.get("operation", "load")
        
        # Mock dataset processing
        await anyio.sleep(0.1)
        
        result = {
            "operation": operation,
            "dataset_path": dataset_path,
            "records_processed": 1000,
            "processing_time": 0.1
        }
        
        return {
            "success": True,
            "result": result,
            "context_updates": {"dataset_info": result}
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _execute_vector_step(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute vector indexing step."""
    try:
        index_type = params.get("index_type", "faiss")
        dimension = params.get("dimension", 384)
        
        # Mock vector indexing
        await anyio.sleep(0.1)
        
        result = {
            "index_type": index_type,
            "dimension": dimension,
            "vectors_indexed": 1000,
            "index_size": "2.3 MB"
        }
        
        return {
            "success": True,
            "result": result,
            "context_updates": {"vector_index": result}
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _execute_ipfs_step(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute IPFS operation step."""
    try:
        operation = params.get("operation", "pin")
        content_hash = params.get("content_hash") or context.get("content_hash")
        
        # Mock IPFS operation
        await anyio.sleep(0.1)
        
        result = {
            "operation": operation,
            "content_hash": content_hash or "QmExampleHash123",
            "status": "success"
        }
        
        return {
            "success": True,
            "result": result,
            "context_updates": {"ipfs_result": result}
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _execute_conditional_step(params: Dict[str, Any], context: Dict[str, Any], step_results: Dict[str, Any]) -> Dict[str, Any]:
    """Execute conditional logic step."""
    try:
        condition = params.get("condition", "true")
        then_action = params.get("then", {})
        else_action = params.get("else", {})
        
        # Simple condition evaluation (in production, use a proper expression evaluator)
        condition_result = eval(condition.replace("context.", "context.get('").replace(".", "', {}).get('"))
        
        action = then_action if condition_result else else_action
        
        return {
            "success": True,
            "result": {
                "condition": condition,
                "condition_result": condition_result,
                "action_taken": "then" if condition_result else "else",
                "action": action
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _execute_parallel_step(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute parallel operations step."""
    try:
        sub_steps = params.get("sub_steps", [])
        max_workers = params.get("max_workers", 3)
        
        # Execute sub-steps in parallel
        semaphore = anyio.Semaphore(max_workers)
        
        async def execute_sub_step(sub_step):
            async with semaphore:
                return await _execute_generic_step(sub_step.get("type"), sub_step.get("parameters", {}), context)
                
        results = [None] * len(sub_steps)

        async def _run_one(idx: int, sub_step) -> None:
            try:
                results[idx] = await execute_sub_step(sub_step)
            except Exception as e:
                results[idx] = e

        async with anyio.create_task_group() as tg:
            for idx, sub_step in enumerate(sub_steps):
                tg.start_soon(_run_one, idx, sub_step)
        
        # Collect results
        sub_step_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                sub_step_results.append({"success": False, "error": str(result)})
            else:
                sub_step_results.append(result)
                
        return {
            "success": True,
            "result": {
                "sub_steps_executed": len(sub_steps),
                "sub_step_results": sub_step_results
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _execute_generic_step(step_type: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a generic workflow step."""
    try:
        # Mock generic step execution
        await anyio.sleep(0.05)
        
        return {
            "success": True,
            "result": {
                "step_type": step_type,
                "parameters": params,
                "message": f"Generic step '{step_type}' executed successfully"
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _process_single_dataset(dataset_config: Dict[str, Any], pipeline: List[str]) -> Dict[str, Any]:
    """Process a single dataset through the pipeline."""
    try:
        dataset_id = dataset_config.get("id", "unknown")
        
        # Mock dataset processing through pipeline
        results = {}
        for step in pipeline:
            await anyio.sleep(0.02)  # Simulate processing time
            results[step] = f"Completed {step} for dataset {dataset_id}"
            
        return {
            "dataset_id": dataset_id,
            "success": True,
            "pipeline_results": results,
            "processing_time": len(pipeline) * 0.02
        }
    except Exception as e:
        return {
            "dataset_id": dataset_config.get("id", "unknown"),
            "success": False,
            "error": str(e)
        }
