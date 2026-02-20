#!/usr/bin/env python3

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.development_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.automated_pr_review_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.development_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

# -*- coding: utf-8 -*-
"""
Automated PR Review MCP Tools

This module provides MCP (Model Context Protocol) tool wrappers for the
automated PR review system that uses GitHub Copilot agents.

Available tools:
- AutomatedPRReviewTool: Automatically review all open PRs
- AnalyzePRTool: Analyze a specific PR
- InvokeCopilotOnPRTool: Invoke Copilot on a specific PR
"""

import logging
import sys
import os
from typing import Dict, Any, List
from pathlib import Path

# Add scripts directory to path
scripts_dir = Path(__file__).parent.parent.parent / 'scripts'
sys.path.insert(0, str(scripts_dir))

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

class AutomatedPRReviewTool(ClaudeMCPTool):
    """
    Tool for automatically reviewing all open PRs with GitHub Copilot.
    
    Scans all open PRs and intelligently decides whether to invoke Copilot
    coding agents based on multiple criteria.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "automated_pr_review"
        self.description = "Automatically review all open PRs and invoke GitHub Copilot agents where appropriate"
        self.category = "development"
        self.tags = ["github", "copilot", "pr", "review", "automation", "ci-cd"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, only show what would be done without invoking Copilot",
                    "default": False
                },
                "min_confidence": {
                    "type": "integer",
                    "description": "Minimum confidence score (0-100) to invoke Copilot",
                    "default": 60,
                    "minimum": 0,
                    "maximum": 100
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of PRs to process",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 200
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute automated PR review.
        
        Args:
            parameters: Tool parameters with dry_run, min_confidence, and limit
        
        Returns:
            Dictionary with review results and statistics
        """
        try:
            from automated_pr_review import AutomatedPRReviewer
            
            dry_run = parameters.get("dry_run", False)
            min_confidence = parameters.get("min_confidence", 60)
            limit = parameters.get("limit", 100)
            
            # Create reviewer
            reviewer = AutomatedPRReviewer(
                dry_run=dry_run,
                min_confidence=min_confidence
            )
            
            # Review all PRs
            stats = reviewer.review_all_prs(limit=limit)
            
            return {
                "success": True,
                "dry_run": dry_run,
                "min_confidence": min_confidence,
                "statistics": {
                    "total_prs": stats['total'],
                    "analyzed": stats['analyzed'],
                    "copilot_invoked": stats['invoked'],
                    "skipped": stats['skipped'],
                    "failed": stats['failed']
                },
                "results": stats.get('results', [])
            }
        
        except Exception as e:
            logger.error(f"Failed to execute automated PR review: {e}")
            return {
                "success": False,
                "error": str(e)
            }

class AnalyzePRTool(ClaudeMCPTool):
    """
    Tool for analyzing a specific PR to determine if Copilot should be invoked.
    
    Provides detailed analysis without actually invoking Copilot.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "analyze_pr"
        self.description = "Analyze a specific PR to determine if GitHub Copilot should be invoked"
        self.category = "development"
        self.tags = ["github", "copilot", "pr", "analysis"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "pr_number": {
                    "type": "integer",
                    "description": "PR number to analyze",
                    "minimum": 1
                },
                "min_confidence": {
                    "type": "integer",
                    "description": "Minimum confidence score (0-100) for recommendation",
                    "default": 60,
                    "minimum": 0,
                    "maximum": 100
                }
            },
            "required": ["pr_number"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a specific PR.
        
        Args:
            parameters: Tool parameters with pr_number and min_confidence
        
        Returns:
            Dictionary with analysis results
        """
        try:
            from automated_pr_review import AutomatedPRReviewer
            
            pr_number = parameters.get("pr_number")
            min_confidence = parameters.get("min_confidence", 60)
            
            if not pr_number:
                return {
                    "success": False,
                    "error": "pr_number is required"
                }
            
            # Create reviewer in dry-run mode for analysis
            reviewer = AutomatedPRReviewer(
                dry_run=True,
                min_confidence=min_confidence
            )
            
            # Get PR details
            pr_details = reviewer.get_pr_details(pr_number)
            if not pr_details:
                return {
                    "success": False,
                    "error": f"Failed to get details for PR #{pr_number}"
                }
            
            # Check if already invoked
            already_invoked = reviewer.check_copilot_already_invoked(pr_details)
            
            # Analyze the PR
            analysis = reviewer.analyze_pr(pr_details)
            
            return {
                "success": True,
                "pr_number": pr_number,
                "pr_title": pr_details['title'],
                "is_draft": pr_details['isDraft'],
                "copilot_already_invoked": already_invoked,
                "analysis": {
                    "should_invoke": analysis['should_invoke'],
                    "confidence": analysis['confidence'],
                    "task_type": analysis['task_type'],
                    "reasons": analysis['reasons'],
                    "criteria_scores": analysis['criteria_scores']
                },
                "recommendation": (
                    f"Invoke Copilot ({analysis['confidence']}% confidence)"
                    if analysis['should_invoke']
                    else f"Skip ({analysis['confidence']}% confidence, threshold: {min_confidence}%)"
                )
            }
        
        except Exception as e:
            logger.error(f"Failed to analyze PR: {e}")
            return {
                "success": False,
                "error": str(e)
            }

class InvokeCopilotOnPRTool(ClaudeMCPTool):
    """
    Tool for invoking GitHub Copilot on a specific PR.
    
    Analyzes the PR and invokes Copilot if criteria are met.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "invoke_copilot_on_pr"
        self.description = "Invoke GitHub Copilot coding agent on a specific PR"
        self.category = "development"
        self.tags = ["github", "copilot", "pr", "invoke"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "pr_number": {
                    "type": "integer",
                    "description": "PR number to invoke Copilot on",
                    "minimum": 1
                },
                "force": {
                    "type": "boolean",
                    "description": "Force invocation even if confidence is low",
                    "default": False
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, only show what would be done",
                    "default": False
                }
            },
            "required": ["pr_number"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Invoke Copilot on a specific PR.
        
        Args:
            parameters: Tool parameters with pr_number, force, and dry_run
        
        Returns:
            Dictionary with invocation results
        """
        try:
            from automated_pr_review import AutomatedPRReviewer
            
            pr_number = parameters.get("pr_number")
            force = parameters.get("force", False)
            dry_run = parameters.get("dry_run", False)
            
            if not pr_number:
                return {
                    "success": False,
                    "error": "pr_number is required"
                }
            
            # Create reviewer
            min_confidence = 0 if force else 60
            reviewer = AutomatedPRReviewer(
                dry_run=dry_run,
                min_confidence=min_confidence
            )
            
            # Invoke Copilot on the PR
            result = reviewer.invoke_copilot_on_pr(pr_number)
            
            return {
                "success": result['success'],
                "pr_number": pr_number,
                "action": result.get('action'),
                "dry_run": dry_run,
                "forced": force,
                "confidence": result.get('confidence'),
                "task_type": result.get('task_type'),
                "reason": result.get('reason'),
                "error": result.get('error')
            }
        
        except Exception as e:
            logger.error(f"Failed to invoke Copilot on PR: {e}")
            return {
                "success": False,
                "error": str(e)
            }

# Export all tools
__all__ = [
    'AutomatedPRReviewTool',
    'AnalyzePRTool',
    'InvokeCopilotOnPRTool'
]
