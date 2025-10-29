"""
AI Agent PR Creation Tool for Software Engineering Dashboard.

This module provides tools for creating GitHub pull requests from AI agents
(like GitHub Copilot, Claude Code, Gemini Code, etc.) that are using this
package as an MCP server.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def create_ai_agent_pr(
    owner: str,
    repo: str,
    branch_name: str,
    title: str,
    description: str,
    changes_summary: List[Dict[str, Any]],
    agent_name: str = "AI Agent",
    base_branch: str = "main",
    draft: bool = False,
    labels: Optional[List[str]] = None,
    auto_merge: bool = False
) -> Dict[str, Any]:
    """
    Create a GitHub pull request from an AI agent workflow.
    
    This function is designed to be used by AI coding assistants (GitHub Copilot,
    Claude Code, Gemini Code, etc.) to create pull requests programmatically
    when using this package as an MCP server tool.
    
    Args:
        owner: Repository owner (username or organization)
        repo: Repository name
        branch_name: Name of the branch with changes
        title: Pull request title
        description: Pull request description
        changes_summary: List of changes made, each with:
            - file: File path
            - action: 'added', 'modified', 'deleted'
            - description: Change description
        agent_name: Name of the AI agent creating the PR (e.g., "GitHub Copilot", "Claude Code")
        base_branch: Target branch for PR (default: "main")
        draft: Create as draft PR (default: False)
        labels: Optional labels to apply
        auto_merge: Enable auto-merge if checks pass (default: False)
        
    Returns:
        Dictionary with PR creation result including PR URL and number
        
    Example:
        >>> result = create_ai_agent_pr(
        ...     owner="myorg",
        ...     repo="myrepo",
        ...     branch_name="copilot/add-feature",
        ...     title="Add new analysis feature",
        ...     description="Implements XYZ analysis",
        ...     changes_summary=[
        ...         {"file": "analyzer.py", "action": "modified", "description": "Added XYZ method"},
        ...         {"file": "test_analyzer.py", "action": "added", "description": "Added tests"}
        ...     ],
        ...     agent_name="GitHub Copilot",
        ...     labels=["ai-generated", "enhancement"]
        ... )
    """
    try:
        # Import the GitHub CLI tool
        from .github_cli_server_tools import github_create_pull_request
        
        # Format PR body with agent attribution and changes summary
        pr_body = f"# {agent_name} Generated Pull Request\n\n"
        pr_body += f"{description}\n\n"
        pr_body += "## Changes Summary\n\n"
        
        for change in changes_summary:
            action_emoji = {
                'added': '✨',
                'modified': '📝',
                'deleted': '🗑️'
            }.get(change.get('action', 'modified'), '📝')
            
            pr_body += f"- {action_emoji} **{change.get('file')}**: {change.get('description')}\n"
        
        pr_body += f"\n---\n*This PR was created by {agent_name} via MCP server*\n"
        pr_body += f"*Created at: {datetime.utcnow().isoformat()}*\n"
        
        # Add default labels for AI-generated PRs
        if labels is None:
            labels = []
        if "ai-generated" not in labels:
            labels.append("ai-generated")
        
        # Create the pull request
        result = github_create_pull_request(
            owner=owner,
            repo=repo,
            title=title,
            body=pr_body,
            head=branch_name,
            base=base_branch,
            draft=draft,
            labels=labels
        )
        
        if not result.get("success"):
            return result
        
        # If auto-merge is requested, enable it
        if auto_merge and result.get("pr_url"):
            # Note: Auto-merge requires GitHub CLI with proper permissions
            pr_number = _extract_pr_number(result.get("pr_url", ""))
            if pr_number:
                _enable_auto_merge(owner, repo, pr_number)
        
        # Add additional metadata to result
        result["agent_name"] = agent_name
        result["branch_name"] = branch_name
        result["changes_count"] = len(changes_summary)
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to create AI agent PR: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def update_ai_agent_pr(
    owner: str,
    repo: str,
    pr_number: int,
    updates: Dict[str, Any],
    agent_name: str = "AI Agent"
) -> Dict[str, Any]:
    """
    Update an existing AI agent pull request.
    
    Allows AI agents to iteratively update PRs based on feedback,
    code review comments, or additional analysis.
    
    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number
        updates: Dictionary with updates to apply:
            - title: New title (optional)
            - description: New description (optional)
            - add_changes: List of additional changes (optional)
            - add_labels: Labels to add (optional)
            - remove_labels: Labels to remove (optional)
        agent_name: Name of the AI agent
        
    Returns:
        Dictionary with update result
        
    Example:
        >>> result = update_ai_agent_pr(
        ...     owner="myorg",
        ...     repo="myrepo",
        ...     pr_number=123,
        ...     updates={
        ...         "description": "Updated with additional analysis",
        ...         "add_changes": [{"file": "new_file.py", "action": "added", "description": "New module"}],
        ...         "add_labels": ["ready-for-review"]
        ...     },
        ...     agent_name="Claude Code"
        ... )
    """
    try:
        from .github_cli_server_tools import github_update_pull_request, github_get_pull_requests
        
        # Get current PR info
        prs_result = github_get_pull_requests(owner, repo, state="all")
        if not prs_result.get("success"):
            return prs_result
        
        current_pr = next((pr for pr in prs_result.get("pull_requests", []) 
                          if pr.get("number") == pr_number), None)
        
        if not current_pr:
            return {
                "success": False,
                "error": f"Pull request #{pr_number} not found"
            }
        
        # Build updated body if needed
        new_body = None
        if updates.get("description") or updates.get("add_changes"):
            current_body = current_pr.get("body", "")
            
            # Update description if provided
            if updates.get("description"):
                # Replace the description section
                lines = current_body.split('\n')
                new_lines = [f"# {agent_name} Generated Pull Request\n"]
                new_lines.append(f"{updates['description']}\n")
                
                # Keep changes summary if it exists
                if "## Changes Summary" in current_body:
                    summary_start = current_body.index("## Changes Summary")
                    new_lines.append(current_body[summary_start:])
                
                new_body = '\n'.join(new_lines)
            
            # Add new changes to summary if provided
            if updates.get("add_changes"):
                if not new_body:
                    new_body = current_body
                
                changes_text = "\n"
                for change in updates["add_changes"]:
                    action_emoji = {
                        'added': '✨',
                        'modified': '📝',
                        'deleted': '🗑️'
                    }.get(change.get('action', 'modified'), '📝')
                    
                    changes_text += f"- {action_emoji} **{change.get('file')}**: {change.get('description')}\n"
                
                # Insert before the footer
                if "---\n*This PR was created by" in new_body:
                    footer_start = new_body.index("---\n*This PR was created by")
                    new_body = new_body[:footer_start] + changes_text + "\n" + new_body[footer_start:]
                else:
                    new_body += changes_text
        
        # Update the PR
        result = github_update_pull_request(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            title=updates.get("title"),
            body=new_body,
            add_labels=updates.get("add_labels"),
            remove_labels=updates.get("remove_labels")
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to update AI agent PR: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def analyze_code_for_pr(
    file_paths: List[str],
    analysis_type: str = "comprehensive"
) -> Dict[str, Any]:
    """
    Analyze code changes for PR creation.
    
    Runs code analysis tools on changed files to generate comprehensive
    information for PR descriptions and review.
    
    Args:
        file_paths: List of file paths to analyze
        analysis_type: Type of analysis to perform:
            - "comprehensive": Full analysis including linting, tests, docs
            - "quick": Fast analysis for basic issues
            - "security": Focus on security issues
        
    Returns:
        Dictionary with analysis results and PR recommendations
        
    Example:
        >>> result = analyze_code_for_pr(
        ...     file_paths=["analyzer.py", "test_analyzer.py"],
        ...     analysis_type="comprehensive"
        ... )
        >>> print(result['pr_recommendations'])
    """
    try:
        from ..development_tools.linting_tools import lint_python_codebase
        from ..development_tools.test_generator import test_generator
        
        analysis_result = {
            "success": True,
            "files_analyzed": len(file_paths),
            "issues": [],
            "test_coverage": {},
            "pr_recommendations": [],
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
        # Run linting
        if analysis_type in ["comprehensive", "quick"]:
            lint_result = lint_python_codebase(
                path=".",
                files=file_paths,
                fix_issues=False
            )
            
            if lint_result.get("success"):
                analysis_result["linting"] = lint_result
                if lint_result.get("issues"):
                    analysis_result["issues"].extend(lint_result["issues"])
                    analysis_result["pr_recommendations"].append({
                        "type": "linting",
                        "message": f"Found {len(lint_result['issues'])} linting issues",
                        "action": "Fix linting issues before merging"
                    })
        
        # Generate test recommendations
        if analysis_type == "comprehensive":
            for file_path in file_paths:
                if file_path.endswith('.py') and not file_path.startswith('test_'):
                    analysis_result["pr_recommendations"].append({
                        "type": "testing",
                        "message": f"Consider adding tests for {file_path}",
                        "action": "Use test_generator tool to create tests"
                    })
        
        # Security analysis
        if analysis_type == "security":
            # Check for common security patterns
            security_patterns = [
                ("eval(", "Avoid using eval() - security risk"),
                ("exec(", "Avoid using exec() - security risk"),
                ("pickle.loads", "Be careful with pickle.loads - potential code execution"),
                ("yaml.load", "Use yaml.safe_load instead of yaml.load"),
            ]
            
            for file_path in file_paths:
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                        for pattern, warning in security_patterns:
                            if pattern in content:
                                analysis_result["issues"].append({
                                    "file": file_path,
                                    "type": "security",
                                    "pattern": pattern,
                                    "warning": warning
                                })
                except Exception as e:
                    logger.warning(f"Could not read {file_path}: {e}")
        
        return analysis_result
        
    except Exception as e:
        logger.error(f"Failed to analyze code for PR: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def _extract_pr_number(pr_url: str) -> Optional[int]:
    """Extract PR number from GitHub URL."""
    try:
        # URL format: https://github.com/owner/repo/pull/123
        parts = pr_url.rstrip('/').split('/')
        if 'pull' in parts:
            idx = parts.index('pull')
            return int(parts[idx + 1])
    except (ValueError, IndexError):
        pass
    return None


def _enable_auto_merge(owner: str, repo: str, pr_number: int) -> bool:
    """Enable auto-merge for a PR (requires GitHub CLI with proper permissions)."""
    try:
        from ..development_tools.github_cli_server_tools import github_cli_execute
        
        result = github_cli_execute(
            command=['pr', 'merge', str(pr_number), '--auto', '--squash', 
                     '--repo', f'{owner}/{repo}'],
            install_dir=None
        )
        
        return result.get("success", False)
    except Exception as e:
        logger.warning(f"Could not enable auto-merge: {e}")
        return False
