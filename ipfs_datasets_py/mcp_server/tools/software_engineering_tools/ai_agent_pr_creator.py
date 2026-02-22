"""
AI Agent PR Creation Tool for Software Engineering Dashboard (thin wrapper).

Business logic lives in ipfs_datasets_py.processors.development.ai_agent_pr_engine.
"""
from __future__ import annotations

from ipfs_datasets_py.processors.development.ai_agent_pr_engine import (  # noqa: F401
    analyze_code_for_pr,
    create_ai_agent_pr,
    update_ai_agent_pr,
)

__all__ = ["create_ai_agent_pr", "update_ai_agent_pr", "analyze_code_for_pr"]
