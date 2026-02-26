from importlib import import_module

"""Workflow automation core.

This package intentionally contains MCP-agnostic workflow logic so it can be reused
by CLI, MCP tools, and other integrations.
"""


_enhanced = import_module(".enhanced_workflows", __package__)
_background = import_module(".background_task_engine", __package__)

# Background task exports
TaskStatus = _background.TaskStatus
TaskType = _background.TaskType
MockBackgroundTask = _background.MockBackgroundTask
MockTaskManager = _background.MockTaskManager

# Workflow exports
WorkflowStatus = _enhanced.WorkflowStatus
StepStatus = _enhanced.StepStatus
WorkflowStep = _enhanced.WorkflowStep
WorkflowDefinition = _enhanced.WorkflowDefinition
MockWorkflowService = _enhanced.MockWorkflowService
get_default_workflow_service = _enhanced.get_default_workflow_service

__all__ = [
    "TaskStatus",
    "TaskType",
    "MockBackgroundTask",
    "MockTaskManager",
    "WorkflowStatus",
    "StepStatus",
    "WorkflowStep",
    "WorkflowDefinition",
    "MockWorkflowService",
    "get_default_workflow_service",
]