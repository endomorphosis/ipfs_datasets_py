# ipfs_datasets_py/mcp_server/tools/workflow_tools/workflow_tools.py
"""
Workflow automation and pipeline management tools.
Migrated from ipfs_embeddings_py project.
"""

import logging
import anyio
import uuid
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

# Workflow state tracking
WORKFLOW_REGISTRY = {}
EXECUTION_HISTORY = {}


async def execute_workflow(
    workflow_definition: Dict[str, Any],
    workflow_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute a multi-step workflow with conditional logic and error handling.
    
    Args:
        workflow_definition: Dictionary defining workflow steps and logic
        workflow_id: Optional workflow ID (generated if not provided)
        context: Additional context data for workflow execution
        
    Returns:
        Dict containing workflow execution results
    """
    try:
        # Generate workflow ID if not provided
        if not workflow_id:
            workflow_id = f"workflow_{uuid.uuid4().hex[:8]}"
            
        # Initialize workflow tracking
        start_time = datetime.now()
        WORKFLOW_REGISTRY[workflow_id] = {
            "definition": workflow_definition,
            "status": "running",
            "start_time": start_time.isoformat(),
            "context": context or {}
        }
        
        # Extract workflow steps
        steps = workflow_definition.get("steps", [])
        if not steps:
            return {
                "success": False,
                "workflow_id": workflow_id,
                "error": "No steps defined in workflow",
                "timestamp": datetime.now().isoformat()
            }
            
        # Execute workflow steps
        step_results = {}
        workflow_context = context or {}
        
        for i, step in enumerate(steps):
            step_id = step.get("id", f"step_{i}")
            step_type = step.get("type", "unknown")
            step_params = step.get("parameters", {})
            
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
                        "workflow_id": workflow_id,
                        "error": f"Workflow failed at critical step {step_id}: {str(e)}",
                        "step_results": step_results,
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
            "workflow_id": workflow_id,
            "step_results": step_results,
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
            tasks = [process_dataset(dataset) for dataset in batch_datasets]
            batch_task_results = await asyncio.gather(*tasks, return_exceptions=True)
            
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
    workflow_definition: Dict[str, Any],
    schedule_config: Dict[str, Any]
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
        
        # Validate schedule configuration
        schedule_type = schedule_config.get("type", "once")
        
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


async def get_workflow_status(workflow_id: str) -> Dict[str, Any]:
    """
    Get the status and results of a workflow execution.
    
    Args:
        workflow_id: ID of the workflow to check
        
    Returns:
        Dict containing workflow status and details
    """
    try:
        if workflow_id not in WORKFLOW_REGISTRY:
            return {
                "success": False,
                "workflow_id": workflow_id,
                "error": "Workflow not found",
                "available_workflows": list(WORKFLOW_REGISTRY.keys())[-5:]  # Show last 5
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
                
        tasks = [execute_sub_step(sub_step) for sub_step in sub_steps]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
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
