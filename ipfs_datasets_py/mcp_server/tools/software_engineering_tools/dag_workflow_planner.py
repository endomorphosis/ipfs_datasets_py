"""
DAG Workflow Planner for Software Engineering Dashboard.

This module provides tools for DAG-based workflow planning and orchestration,
including the concept of "dagseq2dagseq" for speculative execution planning.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def create_workflow_dag(
    tasks: List[Dict[str, Any]],
    validate: bool = True
) -> Dict[str, Any]:
    """
    Create a DAG (Directed Acyclic Graph) representation of a workflow.
    
    Takes a list of tasks with dependencies and creates a DAG structure
    suitable for workflow orchestration and execution planning.
    
    Args:
        tasks: List of task dictionaries, each containing:
            - id: Unique task identifier
            - name: Task name
            - dependencies: List of task IDs that must complete before this task
            - estimated_duration: Estimated duration in seconds (optional)
            - resources: Dict of required resources (optional)
        validate: Whether to validate the DAG for cycles
        
    Returns:
        Dictionary containing DAG representation with keys:
        - dag: The directed acyclic graph structure
        - execution_order: Topologically sorted execution order
        - parallel_groups: Groups of tasks that can run in parallel
        - critical_path: Critical path through the DAG
        - estimated_total_duration: Total estimated duration
        
    Example:
        >>> tasks = [
        ...     {"id": "build", "name": "Build", "dependencies": [], "estimated_duration": 300},
        ...     {"id": "test", "name": "Test", "dependencies": ["build"], "estimated_duration": 600},
        ...     {"id": "deploy", "name": "Deploy", "dependencies": ["test"], "estimated_duration": 180}
        ... ]
        >>> dag = create_workflow_dag(tasks)
        >>> print(f"Execution order: {dag['execution_order']}")
    """
    try:
        result = {
            "success": True,
            "dag": {},
            "execution_order": [],
            "parallel_groups": [],
            "critical_path": [],
            "estimated_total_duration": 0,
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Build DAG structure
        dag = {}
        for task in tasks:
            task_id = task.get("id")
            if not task_id:
                continue
            
            dag[task_id] = {
                "name": task.get("name", task_id),
                "dependencies": task.get("dependencies", []),
                "estimated_duration": task.get("estimated_duration", 0),
                "resources": task.get("resources", {}),
                "dependents": []
            }
        
        # Build dependents (reverse edges)
        for task_id, task_data in dag.items():
            for dep in task_data["dependencies"]:
                if dep in dag:
                    dag[dep]["dependents"].append(task_id)
        
        result["dag"] = dag
        
        # Validate for cycles if requested
        if validate:
            has_cycle, cycle = _detect_cycle(dag)
            if has_cycle:
                return {
                    "success": False,
                    "error": "Cycle detected in DAG",
                    "cycle": cycle
                }
        
        # Compute topological sort (execution order)
        execution_order = _topological_sort(dag)
        result["execution_order"] = execution_order
        
        # Compute parallel groups
        parallel_groups = _compute_parallel_groups(dag, execution_order)
        result["parallel_groups"] = parallel_groups
        
        # Compute critical path
        critical_path = _compute_critical_path(dag, execution_order)
        result["critical_path"] = critical_path
        
        # Estimate total duration (critical path duration)
        total_duration = sum(dag[task_id]["estimated_duration"] for task_id in critical_path)
        result["estimated_total_duration"] = total_duration
        
        return result
        
    except Exception as e:
        logger.error(f"Error creating workflow DAG: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def plan_speculative_execution(
    dag_result: Dict[str, Any],
    available_resources: Dict[str, int],
    predict_future_dags: bool = True
) -> Dict[str, Any]:
    """
    Plan speculative execution for workflow DAGs (dagseq2dagseq concept).
    
    Analyzes a workflow DAG and plans resource provisioning for speculative
    execution, predicting future resource needs based on current execution position.
    This implements the "dagseq2dagseq" concept for predictive resource allocation.
    
    Args:
        dag_result: Result from create_workflow_dag
        available_resources: Dict of currently available resources
            Example: {"cpu": 16, "memory_gb": 64, "gpu": 4}
        predict_future_dags: Whether to predict future DAG requirements
        
    Returns:
        Dictionary containing execution plan with keys:
        - execution_plan: Ordered execution plan with resource allocations
        - resource_predictions: Predicted resource needs at each stage
        - gpu_provisioning_schedule: Schedule for GPU provisioning
        - bottlenecks: Identified resource bottlenecks
        
    Example:
        >>> dag = create_workflow_dag(tasks)
        >>> resources = {"cpu": 32, "memory_gb": 128, "gpu": 8}
        >>> plan = plan_speculative_execution(dag, resources)
        >>> print(f"GPU provisioning schedule: {plan['gpu_provisioning_schedule']}")
    """
    try:
        if not dag_result.get("success"):
            return {
                "success": False,
                "error": "Invalid DAG result provided"
            }
        
        result = {
            "success": True,
            "execution_plan": [],
            "resource_predictions": [],
            "gpu_provisioning_schedule": [],
            "bottlenecks": [],
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
        dag = dag_result.get("dag", {})
        parallel_groups = dag_result.get("parallel_groups", [])
        
        # Plan execution with resource allocation
        cumulative_time = 0
        for group_idx, group in enumerate(parallel_groups):
            group_plan = {
                "group_id": group_idx,
                "tasks": [],
                "start_time": cumulative_time,
                "estimated_duration": 0
            }
            
            max_duration = 0
            total_resources_needed = {"cpu": 0, "memory_gb": 0, "gpu": 0}
            
            for task_id in group:
                task = dag.get(task_id, {})
                duration = task.get("estimated_duration", 0)
                resources = task.get("resources", {})
                
                task_plan = {
                    "task_id": task_id,
                    "name": task.get("name", task_id),
                    "estimated_duration": duration,
                    "required_resources": resources
                }
                
                group_plan["tasks"].append(task_plan)
                max_duration = max(max_duration, duration)
                
                # Accumulate resource needs
                for resource, amount in resources.items():
                    total_resources_needed[resource] = \
                        total_resources_needed.get(resource, 0) + amount
            
            group_plan["estimated_duration"] = max_duration
            group_plan["total_resources_needed"] = total_resources_needed
            
            # Check for resource bottlenecks
            for resource, needed in total_resources_needed.items():
                available = available_resources.get(resource, 0)
                if needed > available:
                    result["bottlenecks"].append({
                        "group_id": group_idx,
                        "resource": resource,
                        "needed": needed,
                        "available": available,
                        "shortage": needed - available
                    })
            
            result["execution_plan"].append(group_plan)
            cumulative_time += max_duration
            
            # Predict future GPU needs (speculative)
            if predict_future_dags and group_idx < len(parallel_groups) - 1:
                # Look ahead to next groups
                future_gpu_need = 0
                for future_group in parallel_groups[group_idx + 1:group_idx + 3]:
                    for task_id in future_group:
                        task = dag.get(task_id, {})
                        future_gpu_need += task.get("resources", {}).get("gpu", 0)
                
                if future_gpu_need > 0:
                    result["gpu_provisioning_schedule"].append({
                        "provision_at": cumulative_time,
                        "gpus_needed": future_gpu_need,
                        "reason": f"Predicted need for groups {group_idx + 1} to {group_idx + 3}"
                    })
        
        return result
        
    except Exception as e:
        logger.error(f"Error planning speculative execution: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def _detect_cycle(dag: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Detect if there's a cycle in the DAG."""
    visited = set()
    rec_stack = set()
    
    def dfs(node: str, path: List[str]) -> Tuple[bool, List[str]]:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        
        for dep in dag.get(node, {}).get("dependents", []):
            if dep not in visited:
                has_cycle, cycle = dfs(dep, path.copy())
                if has_cycle:
                    return True, cycle
            elif dep in rec_stack:
                # Found cycle
                cycle_start = path.index(dep)
                return True, path[cycle_start:] + [dep]
        
        rec_stack.remove(node)
        return False, []
    
    for node in dag:
        if node not in visited:
            has_cycle, cycle = dfs(node, [])
            if has_cycle:
                return True, cycle
    
    return False, []


def _topological_sort(dag: Dict[str, Any]) -> List[str]:
    """Perform topological sort on the DAG."""
    in_degree = {node: len(dag[node]["dependencies"]) for node in dag}
    queue = [node for node in dag if in_degree[node] == 0]
    result = []
    
    while queue:
        node = queue.pop(0)
        result.append(node)
        
        for dependent in dag[node]["dependents"]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    
    return result


def _compute_parallel_groups(dag: Dict[str, Any], execution_order: List[str]) -> List[List[str]]:
    """Compute groups of tasks that can execute in parallel."""
    groups = []
    remaining = set(execution_order)
    
    while remaining:
        # Find all tasks whose dependencies are satisfied
        current_group = []
        for task in remaining:
            deps = dag[task]["dependencies"]
            if all(dep not in remaining for dep in deps):
                current_group.append(task)
        
        if current_group:
            groups.append(current_group)
            remaining -= set(current_group)
        else:
            break
    
    return groups


def _compute_critical_path(dag: Dict[str, Any], execution_order: List[str]) -> List[str]:
    """Compute the critical path through the DAG."""
    # Simple implementation: find longest path
    longest_path = []
    max_duration = 0
    
    def dfs_longest(node: str, current_path: List[str], current_duration: int):
        nonlocal longest_path, max_duration
        
        current_path.append(node)
        current_duration += dag[node]["estimated_duration"]
        
        if not dag[node]["dependents"]:
            if current_duration > max_duration:
                max_duration = current_duration
                longest_path = current_path.copy()
        else:
            for dependent in dag[node]["dependents"]:
                dfs_longest(dependent, current_path.copy(), current_duration)
    
    # Start from nodes with no dependencies
    for node in dag:
        if not dag[node]["dependencies"]:
            dfs_longest(node, [], 0)
    
    return longest_path
