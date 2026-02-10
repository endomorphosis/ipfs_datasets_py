"""MCP workflow tools (thin wrappers).

Core implementation lives in `ipfs_datasets_py.workflow_automation`.

This file intentionally contains minimal logic so the underlying workflow
functionality is reusable by CLI and other integrations.
"""

from __future__ import annotations

from ipfs_datasets_py.workflow_automation.workflow_api import (
    execute_workflow,
    batch_process_datasets,
    schedule_workflow,
    create_workflow,
    run_workflow,
    get_workflow_status,
    create_template,
    list_templates,
    pause_workflow,
    resume_workflow,
    list_workflows,
    get_workflow_metrics,
    initialize_p2p_scheduler,
    schedule_p2p_workflow,
    get_next_p2p_workflow,
    add_p2p_peer,
    remove_p2p_peer,
    get_p2p_scheduler_status,
    calculate_peer_distance,
    get_workflow_tags,
    merge_merkle_clock,
    get_assigned_workflows,
)

__all__ = [
    "execute_workflow",
    "batch_process_datasets",
    "schedule_workflow",
    "create_workflow",
    "run_workflow",
    "get_workflow_status",
    "create_template",
    "list_templates",
    "pause_workflow",
    "resume_workflow",
    "list_workflows",
    "get_workflow_metrics",
    "initialize_p2p_scheduler",
    "schedule_p2p_workflow",
    "get_next_p2p_workflow",
    "add_p2p_peer",
    "remove_p2p_peer",
    "get_p2p_scheduler_status",
    "calculate_peer_distance",
    "get_workflow_tags",
    "merge_merkle_clock",
    "get_assigned_workflows",
]
