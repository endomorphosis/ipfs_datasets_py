"""Enhanced workflow core types and a small in-memory service.

This code was previously embedded inside the MCP tool module.
Keeping it here makes the logic reusable from CLI and other call sites,
while MCP remains a thin integration layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import anyio


class WorkflowStatus(Enum):
    """Workflow execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class StepStatus(Enum):
    """Individual step status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    """Individual workflow step definition."""

    id: str
    name: str
    type: str
    parameters: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    timeout: int = 3600
    retry_count: int = 0
    max_retries: int = 3
    status: StepStatus = StepStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowDefinition:
    """Complete workflow definition."""

    id: str
    name: str
    description: str
    steps: List[WorkflowStep]
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class MockWorkflowService:
    """In-memory workflow service for development and tests."""

    def __init__(self):
        self.workflows: Dict[str, WorkflowDefinition] = {}
        self.execution_history: List[Dict[str, Any]] = []

    async def create_workflow(self, definition: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new workflow."""

        workflow_id = str(uuid.uuid4())
        workflow = WorkflowDefinition(
            id=workflow_id,
            name=definition.get("name", f"Workflow_{workflow_id[:8]}"),
            description=definition.get("description", ""),
            steps=[
                WorkflowStep(
                    id=step.get("id", str(uuid.uuid4())),
                    name=step.get("name", f"Step_{i}"),
                    type=step.get("type"),
                    parameters=step.get("parameters", {}),
                    dependencies=step.get("dependencies", []) or [],
                    timeout=step.get("timeout", 3600),
                    max_retries=step.get("max_retries", 3),
                )
                for i, step in enumerate(definition.get("steps", []) or [])
            ],
            metadata=definition.get("metadata", {}) or {},
        )

        self.workflows[workflow_id] = workflow
        return {
            "workflow_id": workflow_id,
            "status": workflow.status.value,
            "created_at": workflow.created_at.isoformat(),
            "steps_count": len(workflow.steps),
        }

    async def execute_workflow(
        self, workflow_id: str, execution_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a workflow."""

        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow {workflow_id} not found")

        workflow = self.workflows[workflow_id]
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = datetime.now()

        # Mock execution
        await anyio.sleep(0.1)

        for step in workflow.steps:
            step.status = StepStatus.COMPLETED
            step.start_time = datetime.now()
            step.end_time = datetime.now() + timedelta(seconds=1)
            step.result = {
                "success": True,
                "processed_items": 100,
                "execution_params": execution_params or {},
            }

        workflow.status = WorkflowStatus.COMPLETED
        workflow.completed_at = datetime.now()

        execution_record = {
            "workflow_id": workflow_id,
            "execution_id": str(uuid.uuid4()),
            "status": workflow.status.value,
            "execution_time": (workflow.completed_at - workflow.started_at).total_seconds(),
            "steps_completed": len(
                [s for s in workflow.steps if s.status == StepStatus.COMPLETED]
            ),
            "steps_failed": len([s for s in workflow.steps if s.status == StepStatus.FAILED]),
        }
        self.execution_history.append(execution_record)
        return execution_record

    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status."""

        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow {workflow_id} not found")

        workflow = self.workflows[workflow_id]
        return {
            "workflow_id": workflow_id,
            "name": workflow.name,
            "status": workflow.status.value,
            "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
            "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
            "completed_at": workflow.completed_at.isoformat()
            if workflow.completed_at
            else None,
            "steps": [
                {
                    "id": step.id,
                    "name": step.name,
                    "type": step.type,
                    "status": step.status.value,
                    "start_time": step.start_time.isoformat() if step.start_time else None,
                    "end_time": step.end_time.isoformat() if step.end_time else None,
                    "error": step.error,
                }
                for step in workflow.steps
            ],
        }

    async def list_workflows(self, status_filter: Optional[str] = None) -> Dict[str, Any]:
        """List all workflows."""

        workflows = list(self.workflows.values())
        if status_filter:
            workflows = [w for w in workflows if w.status.value == status_filter]

        return {
            "workflows": [
                {
                    "id": w.id,
                    "name": w.name,
                    "status": w.status.value,
                    "created_at": w.created_at.isoformat() if w.created_at else None,
                    "steps_count": len(w.steps),
                }
                for w in workflows
            ],
            "total_count": len(workflows),
        }


_DEFAULT_SERVICE: Optional[MockWorkflowService] = None


def get_default_workflow_service() -> MockWorkflowService:
    """Return a process-wide default workflow service instance."""

    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = MockWorkflowService()
    return _DEFAULT_SERVICE
