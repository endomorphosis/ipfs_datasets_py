# src/mcp_server/tools/automated_pr_review_tools.py
# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.development_tools.automated_pr_review_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.automated_pr_review_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.development_tools.automated_pr_review_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.mcp_server.tools.development_tools.automated_pr_review_tools import (  # noqa: F401, E402
    automated_pr_review,
    analyze_pr,
    invoke_copilot_on_pr,
    AutomatedPRReviewTool,
    AnalyzePRTool,
    InvokeCopilotOnPRTool,
)

__all__ = [
    "automated_pr_review",
    "analyze_pr",
    "invoke_copilot_on_pr",
    "AutomatedPRReviewTool",
    "AnalyzePRTool",
    "InvokeCopilotOnPRTool",
]
