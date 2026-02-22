"""
DAG Workflow Engine — canonical package module.

Business logic extracted from mcp_server/tools/software_engineering_tools/dag_workflow_planner.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def create_workflow_dag(
    tasks: List[Dict[str, Any]],
    validate: bool = True,
) -> Dict[str, Any]:
    """Create a DAG representation of a workflow."""
    try:
        result: Dict[str, Any] = {
            "success": True,
            "dag": {},
            "execution_order": [],
            "parallel_groups": [],
            "critical_path": [],
            "estimated_total_duration": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        dag: Dict[str, Any] = {}
        for task in tasks:
            task_id = task.get("id")
            if not task_id:
                continue
            dag[task_id] = {
                "name": task.get("name", task_id),
                "dependencies": task.get("dependencies", []),
                "estimated_duration": task.get("estimated_duration", 0),
                "resources": task.get("resources", {}),
                "dependents": [],
            }

        for task_id, task_data in dag.items():
            for dep in task_data["dependencies"]:
                if dep in dag:
                    dag[dep]["dependents"].append(task_id)

        result["dag"] = dag

        if validate:
            has_cycle, cycle = _detect_cycle(dag)
            if has_cycle:
                return {"success": False, "error": "Cycle detected in DAG", "cycle": cycle}

        execution_order = _topological_sort(dag)
        result["execution_order"] = execution_order

        parallel_groups = _compute_parallel_groups(dag, execution_order)
        result["parallel_groups"] = parallel_groups

        critical_path = _compute_critical_path(dag)
        result["critical_path"] = critical_path

        result["estimated_total_duration"] = sum(
            dag[t]["estimated_duration"] for t in critical_path
        )
        return result

    except Exception as e:
        logger.error("Error creating workflow DAG: %s", e)
        return {"success": False, "error": str(e)}


def plan_speculative_execution(
    dag_result: Dict[str, Any],
    available_resources: Dict[str, int],
    predict_future_dags: bool = True,
) -> Dict[str, Any]:
    """Plan speculative execution for workflow DAGs (dagseq2dagseq concept)."""
    try:
        if not dag_result.get("success"):
            return {"success": False, "error": "Invalid DAG result provided"}

        result: Dict[str, Any] = {
            "success": True,
            "execution_plan": [],
            "resource_predictions": [],
            "gpu_provisioning_schedule": [],
            "bottlenecks": [],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        dag = dag_result.get("dag", {})
        parallel_groups = dag_result.get("parallel_groups", [])

        cumulative_time = 0
        for group_idx, group in enumerate(parallel_groups):
            group_plan: Dict[str, Any] = {
                "group_id": group_idx,
                "tasks": [],
                "start_time": cumulative_time,
                "estimated_duration": 0,
            }

            max_duration = 0
            total_resources_needed: Dict[str, int] = {"cpu": 0, "memory_gb": 0, "gpu": 0}

            for task_id in group:
                task = dag.get(task_id, {})
                duration = task.get("estimated_duration", 0)
                resources = task.get("resources", {})
                group_plan["tasks"].append({
                    "task_id": task_id,
                    "name": task.get("name", task_id),
                    "estimated_duration": duration,
                    "required_resources": resources,
                })
                max_duration = max(max_duration, duration)
                for resource, amount in resources.items():
                    total_resources_needed[resource] = (
                        total_resources_needed.get(resource, 0) + amount
                    )

            group_plan["estimated_duration"] = max_duration
            group_plan["total_resources_needed"] = total_resources_needed

            for resource, needed in total_resources_needed.items():
                available = available_resources.get(resource, 0)
                if needed > available:
                    result["bottlenecks"].append({
                        "group_id": group_idx,
                        "resource": resource,
                        "needed": needed,
                        "available": available,
                        "shortage": needed - available,
                    })

            result["execution_plan"].append(group_plan)
            cumulative_time += max_duration

            if predict_future_dags and group_idx < len(parallel_groups) - 1:
                future_gpu_need = 0
                for future_group in parallel_groups[group_idx + 1 : group_idx + 3]:
                    for tid in future_group:
                        future_gpu_need += dag.get(tid, {}).get("resources", {}).get("gpu", 0)
                if future_gpu_need > 0:
                    result["gpu_provisioning_schedule"].append({
                        "provision_at": cumulative_time,
                        "gpus_needed": future_gpu_need,
                        "reason": (
                            f"Predicted need for groups {group_idx + 1} to {group_idx + 3}"
                        ),
                    })

        return result

    except Exception as e:
        logger.error("Error planning speculative execution: %s", e)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _detect_cycle(dag: Dict[str, Any]) -> Tuple[bool, List[str]]:
    visited: Set[str] = set()
    rec_stack: Set[str] = set()

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
    in_degree = {node: len(dag[node]["dependencies"]) for node in dag}
    queue = [node for node in dag if in_degree[node] == 0]
    result: List[str] = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for dependent in dag[node]["dependents"]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    return result


def _compute_parallel_groups(
    dag: Dict[str, Any], execution_order: List[str]
) -> List[List[str]]:
    groups: List[List[str]] = []
    remaining = set(execution_order)
    while remaining:
        current_group = [
            task for task in remaining
            if all(dep not in remaining for dep in dag[task]["dependencies"])
        ]
        if current_group:
            groups.append(current_group)
            remaining -= set(current_group)
        else:
            break
    return groups


def _compute_critical_path(dag: Dict[str, Any]) -> List[str]:
    longest_path: List[str] = []
    max_duration = 0

    def dfs_longest(node: str, current_path: List[str], current_duration: int) -> None:
        nonlocal longest_path, max_duration
        current_path.append(node)
        current_duration += dag[node]["estimated_duration"]
        if not dag[node]["dependents"]:
            if current_duration > max_duration:
                max_duration = current_duration
                longest_path[:] = current_path
        else:
            for dependent in dag[node]["dependents"]:
                dfs_longest(dependent, current_path.copy(), current_duration)

    for node in dag:
        if not dag[node]["dependencies"]:
            dfs_longest(node, [], 0)

    return longest_path
