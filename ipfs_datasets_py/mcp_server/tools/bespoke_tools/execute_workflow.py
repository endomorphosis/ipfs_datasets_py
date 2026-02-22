"""
Execute Workflow MCP Tool — thin shim.

All business logic lives in ipfs_datasets_py.processors.development.bespoke_workflow_engine.
"""
from __future__ import annotations

from ipfs_datasets_py.processors.development.bespoke_workflow_engine import (  # noqa: F401
    execute_workflow,
    get_available_workflows,
)
