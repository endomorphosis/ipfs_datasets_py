"""
Workflow Engine — core P2P workflow scheduling operations.

Business logic extracted from mcplusplus_workflow_tools.py (744 lines → thin wrapper).
All methods can be imported and used independently of the MCP layer.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional MCP++ import (graceful degradation)
# ---------------------------------------------------------------------------
try:
    from ipfs_datasets_py.mcp_server.mcplusplus import (
        get_capabilities,
        workflow_scheduler as wf_module,
    )
    MCPLUSPLUS_AVAILABLE: bool = get_capabilities().get("workflow_scheduler_available", False)
except (ImportError, ModuleNotFoundError):
    MCPLUSPLUS_AVAILABLE = False
    wf_module = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unavailable(wf_id: Optional[str] = None) -> Dict[str, Any]:
    """Standard response when MCP++ workflow scheduler is not available."""
    d: Dict[str, Any] = {"success": False, "error": "MCP++ not available"}
    if wf_id:
        d["workflow_id"] = wf_id
    return d


def _error(e: Exception, wf_id: Optional[str] = None) -> Dict[str, Any]:
    """Standard error response."""
    d: Dict[str, Any] = {"success": False, "error": str(e)}
    if wf_id:
        d["workflow_id"] = wf_id
    return d


def _validate_id(workflow_id: str) -> Optional[Dict[str, Any]]:
    """Return error dict if workflow_id is empty, else None."""
    if not workflow_id:
        return {"success": False, "error": "Missing required parameter: workflow_id"}
    return None


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------

class WorkflowEngine:
    """Core workflow operations, independent of MCP tool layer."""

    async def submit(
        self,
        workflow_id: str,
        name: str,
        steps: List[Dict[str, Any]],
        priority: float = 1.0,
        tags: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Submit a workflow to the P2P network for distributed execution."""
        if not workflow_id or not name or not steps:
            return {"success": False, "error": "Missing required parameters: workflow_id, name, or steps"}

        for step in steps:
            if "step_id" not in step or "action" not in step:
                return {
                    "success": False,
                    "error": f"Invalid step structure — missing step_id or action: {step}",
                }

        if not MCPLUSPLUS_AVAILABLE or wf_module is None:
            logger.info("MCP++ not available — workflow %s stored locally", workflow_id)
            return {
                "success": True,
                "workflow_id": workflow_id,
                "status": "queued_local",
                "peer_assigned": "localhost",
                "message": f"Workflow {workflow_id} queued locally (P2P unavailable)",
                "warning": "MCP++ not available — workflow will execute locally",
            }

        try:
            result = await wf_module.submit_workflow(
                workflow_id=workflow_id,
                name=name,
                steps=steps,
                priority=priority,
                tags=tags or [],
                dependencies=dependencies or [],
                metadata=metadata or {},
            )
            return {
                "success": True,
                "workflow_id": workflow_id,
                "status": "submitted",
                "peer_assigned": result.get("peer_id"),
                "estimated_start_time": result.get("estimated_start"),
                "message": f"Workflow {workflow_id} submitted to P2P network",
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("MCP++ workflow submission failed: %s", e)
            return _error(e, workflow_id)

    async def get_status(
        self,
        workflow_id: str,
        include_steps: bool = True,
        include_metrics: bool = False,
    ) -> Dict[str, Any]:
        """Check the status of a submitted workflow."""
        err = _validate_id(workflow_id)
        if err:
            return err

        if not MCPLUSPLUS_AVAILABLE or wf_module is None:
            return _unavailable(workflow_id)

        try:
            scheduler = wf_module.get_scheduler()
            status_data = await scheduler.get_workflow_status(workflow_id)
            if not status_data:
                return {"success": False, "workflow_id": workflow_id, "error": f"Workflow {workflow_id} not found"}

            result: Dict[str, Any] = {
                "success": True,
                "workflow_id": workflow_id,
                "status": status_data.get("status", "unknown"),
                "progress": status_data.get("progress", 0),
                "current_step": status_data.get("current_step"),
                "peer_id": status_data.get("peer_id"),
                "start_time": status_data.get("start_time"),
                "end_time": status_data.get("end_time"),
            }
            if include_steps:
                result["steps"] = status_data.get("steps", [])
            if include_metrics:
                result["metrics"] = status_data.get("metrics", {})
            return result
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error getting workflow status from MCP++: %s", e)
            return _error(e, workflow_id)

    async def cancel(
        self,
        workflow_id: str,
        reason: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Cancel a running or queued workflow."""
        err = _validate_id(workflow_id)
        if err:
            return err

        if not MCPLUSPLUS_AVAILABLE or wf_module is None:
            return {"success": False, "workflow_id": workflow_id, "error": "MCP++ not available — cannot cancel workflow"}

        try:
            scheduler = wf_module.get_scheduler()
            result = await scheduler.cancel_workflow(workflow_id=workflow_id, reason=reason, force=force)
            return {
                "success": True,
                "workflow_id": workflow_id,
                "status": "cancelled",
                "cancelled_steps": result.get("cancelled_steps", 0),
                "message": f"Workflow {workflow_id} cancelled successfully",
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error cancelling workflow via MCP++: %s", e)
            return _error(e, workflow_id)

    async def list_workflows(
        self,
        status_filter: Optional[str] = None,
        peer_filter: Optional[str] = None,
        tag_filter: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List workflows with optional filtering."""
        if limit < 1 or limit > 1000:
            return {"success": False, "error": "Limit must be between 1 and 1000"}
        if offset < 0:
            return {"success": False, "error": "Offset must be non-negative"}

        if not MCPLUSPLUS_AVAILABLE or wf_module is None:
            return {
                "success": False,
                "error": "MCP++ not available — cannot list workflows",
                "workflows": [],
                "total_count": 0,
                "returned_count": 0,
                "has_more": False,
            }

        try:
            scheduler = wf_module.get_scheduler()
            workflows = await scheduler.list_workflows(
                status=status_filter, peer_id=peer_filter, tags=tag_filter, limit=limit, offset=offset
            )
            return {
                "success": True,
                "workflows": workflows.get("workflows", []),
                "total_count": workflows.get("total_count", 0),
                "returned_count": len(workflows.get("workflows", [])),
                "has_more": workflows.get("has_more", False),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error listing workflows via MCP++: %s", e)
            return {**_error(e), "workflows": [], "total_count": 0, "returned_count": 0, "has_more": False}

    async def get_dependencies(
        self,
        workflow_id: str,
        fmt: str = "json",
    ) -> Dict[str, Any]:
        """Get the dependency DAG for a workflow."""
        err = _validate_id(workflow_id)
        if err:
            return err

        if fmt not in ("json", "dot", "mermaid"):
            return {"success": False, "error": f"Invalid format: {fmt}. Must be one of: json, dot, mermaid"}

        if not MCPLUSPLUS_AVAILABLE or wf_module is None:
            return _unavailable(workflow_id)

        try:
            scheduler = wf_module.get_scheduler()
            dag_data = await scheduler.get_workflow_dag(workflow_id, format=fmt)
            if not dag_data:
                return {"success": False, "workflow_id": workflow_id, "error": f"Workflow {workflow_id} not found or has no dependency data"}
            return {
                "success": True,
                "workflow_id": workflow_id,
                "dag": dag_data.get("dag"),
                "nodes": dag_data.get("nodes", []),
                "edges": dag_data.get("edges", []),
                "critical_path": dag_data.get("critical_path", []),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error getting workflow DAG from MCP++: %s", e)
            return _error(e, workflow_id)

    async def get_result(
        self,
        workflow_id: str,
        include_outputs: bool = True,
        include_logs: bool = False,
    ) -> Dict[str, Any]:
        """Retrieve the result of a completed workflow."""
        err = _validate_id(workflow_id)
        if err:
            return err

        if not MCPLUSPLUS_AVAILABLE or wf_module is None:
            return _unavailable(workflow_id)

        try:
            scheduler = wf_module.get_scheduler()
            result_data = await scheduler.get_workflow_result(
                workflow_id=workflow_id, include_outputs=include_outputs, include_logs=include_logs
            )
            if not result_data:
                return {"success": False, "workflow_id": workflow_id, "error": f"Workflow {workflow_id} not found or not yet completed"}
            response: Dict[str, Any] = {
                "success": True,
                "workflow_id": workflow_id,
                "status": result_data.get("status"),
                "result": result_data.get("result"),
                "execution_time": result_data.get("execution_time"),
            }
            if include_outputs:
                response["outputs"] = result_data.get("outputs", [])
            if include_logs:
                response["logs"] = result_data.get("logs", [])
            return response
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error getting workflow result from MCP++: %s", e)
            return _error(e, workflow_id)
