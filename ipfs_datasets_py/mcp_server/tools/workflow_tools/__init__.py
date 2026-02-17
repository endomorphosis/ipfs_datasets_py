# ipfs_datasets_py/mcp_server/tools/workflow_tools/__init__.py
"""
Workflow automation and pipeline management tools.

These tools provide workflow orchestration, batch processing, and scheduling capabilities.
"""

from .workflow_tools import (
    execute_workflow,
    batch_process_datasets,
    schedule_workflow,
    get_workflow_status,
    initialize_p2p_scheduler,
    schedule_p2p_workflow,
    get_next_p2p_workflow,
    add_p2p_peer,
    remove_p2p_peer,
    get_p2p_scheduler_status,
    calculate_peer_distance,
    get_workflow_tags,
    merge_merkle_clock,
    get_assigned_workflows
)

from .enhanced_workflow_tools import (
    enhanced_workflow_management,
    enhanced_batch_processing,
    enhanced_data_pipeline,
)

__all__ = [
    "execute_workflow",
    "batch_process_datasets",
    "schedule_workflow",
    "get_workflow_status",
    "enhanced_workflow_management",
    "enhanced_batch_processing",
    "enhanced_data_pipeline",
    "initialize_p2p_scheduler",
    "schedule_p2p_workflow",
    "get_next_p2p_workflow",
    "add_p2p_peer",
    "remove_p2p_peer",
    "get_p2p_scheduler_status",
    "calculate_peer_distance",
    "get_workflow_tags",
    "merge_merkle_clock",
    "get_assigned_workflows"
]
