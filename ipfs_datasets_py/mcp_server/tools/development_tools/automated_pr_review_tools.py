#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automated PR Review MCP Tools (thin wrappers).

Business logic delegates to `automated_pr_review.AutomatedPRReviewer` (a scripts-level
helper) which is imported lazily inside each function to avoid hard import failures when
the scripts directory is not on sys.path.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Add scripts directory to path so AutomatedPRReviewer can be found at runtime
_scripts_dir = Path(__file__).parent.parent.parent / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))


async def automated_pr_review(
    dry_run: bool = False,
    min_confidence: int = 60,
    limit: int = 100,
) -> Dict[str, Any]:
    """Automatically review all open PRs and invoke GitHub Copilot agents.

    Args:
        dry_run: If True, show what would be done without invoking Copilot.
        min_confidence: Minimum confidence score (0–100) to invoke Copilot.
        limit: Maximum number of PRs to process.

    Returns:
        Dict with review statistics and results.
    """
    try:
        from automated_pr_review import AutomatedPRReviewer  # type: ignore[import]

        reviewer = AutomatedPRReviewer(dry_run=dry_run, min_confidence=min_confidence)
        stats = reviewer.review_all_prs(limit=limit)
        return {
            "success": True,
            "dry_run": dry_run,
            "min_confidence": min_confidence,
            "statistics": {
                "total_prs": stats["total"],
                "analyzed": stats["analyzed"],
                "copilot_invoked": stats["invoked"],
                "skipped": stats["skipped"],
                "failed": stats["failed"],
            },
            "results": stats.get("results", []),
        }
    except Exception as exc:
        logger.error("automated_pr_review failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def analyze_pr(
    pr_number: int,
    min_confidence: int = 60,
) -> Dict[str, Any]:
    """Analyse a specific PR to determine whether Copilot should be invoked.

    Args:
        pr_number: GitHub PR number to analyse.
        min_confidence: Minimum confidence score for recommendation.

    Returns:
        Dict with PR analysis details.
    """
    try:
        from automated_pr_review import AutomatedPRReviewer  # type: ignore[import]

        reviewer = AutomatedPRReviewer(dry_run=True, min_confidence=min_confidence)
        pr_details = reviewer.get_pr_details(pr_number)
        if not pr_details:
            return {"success": False, "error": f"Failed to get details for PR #{pr_number}"}

        already_invoked = reviewer.check_copilot_already_invoked(pr_details)
        analysis = reviewer.analyze_pr(pr_details)
        return {
            "success": True,
            "pr_number": pr_number,
            "pr_title": pr_details["title"],
            "is_draft": pr_details["isDraft"],
            "copilot_already_invoked": already_invoked,
            "analysis": {
                "should_invoke": analysis["should_invoke"],
                "confidence": analysis["confidence"],
                "reasons": analysis.get("reasons", []),
            },
        }
    except Exception as exc:
        logger.error("analyze_pr failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def invoke_copilot_on_pr(
    pr_number: int,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Invoke GitHub Copilot on a specific PR.

    Args:
        pr_number: GitHub PR number to process.
        dry_run: If True, simulate invocation without actually calling Copilot.

    Returns:
        Dict with invocation result.
    """
    try:
        from automated_pr_review import AutomatedPRReviewer  # type: ignore[import]

        reviewer = AutomatedPRReviewer(dry_run=dry_run)
        pr_details = reviewer.get_pr_details(pr_number)
        if not pr_details:
            return {"success": False, "error": f"Failed to get details for PR #{pr_number}"}

        result = reviewer.invoke_copilot(pr_details)
        return {
            "success": result.get("success", False),
            "pr_number": pr_number,
            "pr_title": pr_details["title"],
            "dry_run": dry_run,
            "invocation_result": result,
        }
    except Exception as exc:
        logger.error("invoke_copilot_on_pr failed: %s", exc)
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Backward-compatible class aliases
# ---------------------------------------------------------------------------

class AutomatedPRReviewTool:  # noqa: E302
    """Thin compatibility shim — wraps automated_pr_review()."""
    name = "automated_pr_review"

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await automated_pr_review(**parameters)


class AnalyzePRTool:
    """Thin compatibility shim — wraps analyze_pr()."""
    name = "analyze_pr"

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await analyze_pr(**parameters)


class InvokeCopilotOnPRTool:
    """Thin compatibility shim — wraps invoke_copilot_on_pr()."""
    name = "invoke_copilot_on_pr"

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await invoke_copilot_on_pr(**parameters)
