"""Workflow automation core.

This package intentionally contains MCP-agnostic workflow logic so it can be reused
by CLI, MCP tools, and other integrations.
"""

from .enhanced_workflows import (
    WorkflowStatus,
    StepStatus,
    WorkflowStep,
    WorkflowDefinition,
    MockWorkflowService,
    get_default_workflow_service,
)

__all__ = [
    "WorkflowStatus",
    "StepStatus",
    "WorkflowStep",
    "WorkflowDefinition",
    "MockWorkflowService",
    "get_default_workflow_service",
]
