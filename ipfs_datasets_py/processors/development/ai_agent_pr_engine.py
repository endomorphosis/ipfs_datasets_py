"""
AI Agent PR Engine — canonical package module for AI-generated GitHub PRs.

Contains pure Python logic for creating and updating GitHub pull requests from
AI agents (GitHub Copilot, Claude Code, Gemini Code, etc.).

The MCP tool at mcp_server/tools/software_engineering_tools/ai_agent_pr_creator.py
is a thin wrapper that imports from here.

Usage::

    from ipfs_datasets_py.processors.development.ai_agent_pr_engine import (
        create_ai_agent_pr,
        update_ai_agent_pr,
        analyze_code_for_pr,
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_pr_number(pr_url: str) -> Optional[int]:
    """Extract PR number from a GitHub pull-request URL."""
    try:
        parts = pr_url.rstrip("/").split("/")
        if "pull" in parts:
            return int(parts[parts.index("pull") + 1])
    except (ValueError, IndexError):
        pass
    return None


def _action_emoji(action: str) -> str:
    return {"added": "✨", "modified": "📝", "deleted": "🗑️"}.get(action, "📝")


def _build_pr_body(
    description: str,
    agent_name: str,
    changes_summary: List[Dict[str, Any]],
) -> str:
    """Return a formatted PR body string."""
    lines: List[str] = [
        f"# {agent_name} Generated Pull Request\n",
        f"{description}\n",
        "## Changes Summary\n",
    ]
    for change in changes_summary:
        emoji = _action_emoji(change.get("action", "modified"))
        lines.append(f"- {emoji} **{change.get('file')}**: {change.get('description')}")
    lines += [
        "",
        "---",
        f"*This PR was created by {agent_name} via MCP server*",
        f"*Created at: {datetime.now(timezone.utc).isoformat()}*",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
    auto_merge: bool = False,
) -> Dict[str, Any]:
    """Create a GitHub pull request from an AI agent workflow.

    Args:
        owner: Repository owner (username or organisation).
        repo: Repository name.
        branch_name: Branch that contains the changes.
        title: Pull request title.
        description: Pull request description / body prose.
        changes_summary: List of ``{file, action, description}`` dicts.
        agent_name: Display name of the AI agent (e.g. "GitHub Copilot").
        base_branch: Target branch (default: "main").
        draft: Whether to create the PR as a draft.
        labels: Labels to apply to the PR.
        auto_merge: Enable auto-merge when checks pass.

    Returns:
        Dict with ``success``, ``pr_url``, ``pr_number``, and metadata fields.
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.github_cli_server_tools import (
            github_create_pull_request,
        )

        pr_body = _build_pr_body(description, agent_name, changes_summary)
        effective_labels: List[str] = list(labels) if labels else []
        if "ai-generated" not in effective_labels:
            effective_labels.append("ai-generated")

        result: Dict[str, Any] = github_create_pull_request(
            owner=owner,
            repo=repo,
            title=title,
            body=pr_body,
            head=branch_name,
            base=base_branch,
            draft=draft,
            labels=effective_labels,
        )

        if not result.get("success"):
            return result

        if auto_merge and result.get("pr_url"):
            pr_number = _extract_pr_number(result.get("pr_url", ""))
            if pr_number:
                _enable_auto_merge(owner, repo, pr_number)

        result["agent_name"] = agent_name
        result["branch_name"] = branch_name
        result["changes_count"] = len(changes_summary)
        return result

    except Exception as exc:
        logger.error("create_ai_agent_pr failed: %s", exc)
        return {"success": False, "error": str(exc)}


def update_ai_agent_pr(
    owner: str,
    repo: str,
    pr_number: int,
    updates: Dict[str, Any],
    agent_name: str = "AI Agent",
) -> Dict[str, Any]:
    """Update an existing AI-agent pull request.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.
        updates: Dict with optional keys: ``title``, ``description``,
            ``add_changes`` (list of change dicts), ``add_labels``, ``remove_labels``.
        agent_name: Display name of the AI agent.

    Returns:
        Dict with update result.
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.github_cli_server_tools import (
            github_get_pull_requests,
            github_update_pull_request,
        )

        prs_result: Dict[str, Any] = github_get_pull_requests(owner, repo, state="all")
        if not prs_result.get("success"):
            return prs_result

        current_pr = next(
            (pr for pr in prs_result.get("pull_requests", []) if pr.get("number") == pr_number),
            None,
        )
        if not current_pr:
            return {"success": False, "error": f"Pull request #{pr_number} not found"}

        new_body: Optional[str] = None
        current_body: str = current_pr.get("body", "")

        if updates.get("description"):
            header = f"# {agent_name} Generated Pull Request\n\n{updates['description']}\n\n"
            if "## Changes Summary" in current_body:
                summary_start = current_body.index("## Changes Summary")
                new_body = header + current_body[summary_start:]
            else:
                new_body = header

        if updates.get("add_changes"):
            body = new_body if new_body is not None else current_body
            extra = "\n".join(
                f"- {_action_emoji(c.get('action', 'modified'))} **{c.get('file')}**: {c.get('description')}"
                for c in updates["add_changes"]
            )
            footer_marker = "---\n*This PR was created by"
            if footer_marker in body:
                idx = body.index(footer_marker)
                new_body = body[:idx] + extra + "\n\n" + body[idx:]
            else:
                new_body = body + "\n" + extra

        return github_update_pull_request(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            title=updates.get("title"),
            body=new_body,
            add_labels=updates.get("add_labels"),
            remove_labels=updates.get("remove_labels"),
        )

    except Exception as exc:
        logger.error("update_ai_agent_pr failed: %s", exc)
        return {"success": False, "error": str(exc)}


def analyze_code_for_pr(
    file_paths: List[str],
    analysis_type: str = "comprehensive",
) -> Dict[str, Any]:
    """Analyse changed source files to produce PR description content.

    Args:
        file_paths: Paths to files to analyse.
        analysis_type: ``"comprehensive"``, ``"quick"``, or ``"security"``.

    Returns:
        Dict with linting results, issues, and PR recommendations.
    """
    try:
        result: Dict[str, Any] = {
            "success": True,
            "files_analyzed": len(file_paths),
            "issues": [],
            "test_coverage": {},
            "pr_recommendations": [],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        if analysis_type in ("comprehensive", "quick"):
            try:
                from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import (
                    lint_python_codebase,
                )

                lint_result: Dict[str, Any] = lint_python_codebase(
                    path=".", files=file_paths, fix_issues=False
                )
                if lint_result.get("success"):
                    result["linting"] = lint_result
                    if lint_result.get("issues"):
                        result["issues"].extend(lint_result["issues"])
                        result["pr_recommendations"].append(
                            {
                                "type": "linting",
                                "message": f"Found {len(lint_result['issues'])} linting issues",
                                "action": "Fix linting issues before merging",
                            }
                        )
            except Exception as exc:
                logger.warning("Linting unavailable: %s", exc)

        if analysis_type == "comprehensive":
            for fp in file_paths:
                if fp.endswith(".py") and not fp.startswith("test_"):
                    result["pr_recommendations"].append(
                        {
                            "type": "testing",
                            "message": f"Consider adding tests for {fp}",
                            "action": "Use test_generator tool to create tests",
                        }
                    )

        if analysis_type == "security":
            _DANGEROUS_PATTERNS = [
                ("eval(", "Avoid using eval() - security risk"),
                ("exec(", "Avoid using exec() - security risk"),
                ("pickle.loads", "Be careful with pickle.loads - potential code execution"),
                ("yaml.load", "Use yaml.safe_load instead of yaml.load"),
            ]
            for fp in file_paths:
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    for pattern, warning in _DANGEROUS_PATTERNS:
                        if pattern in content:
                            result["issues"].append(
                                {"file": fp, "type": "security", "pattern": pattern, "warning": warning}
                            )
                except OSError as exc:
                    logger.warning("Could not read %s: %s", fp, exc)

        return result

    except Exception as exc:
        logger.error("analyze_code_for_pr failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _enable_auto_merge(owner: str, repo: str, pr_number: int) -> bool:
    """Enable auto-merge for a PR via GitHub CLI (best-effort)."""
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.github_cli_server_tools import (
            github_cli_execute,
        )

        result = github_cli_execute(
            command=["pr", "merge", str(pr_number), "--auto", "--squash", "--repo", f"{owner}/{repo}"],
            install_dir=None,
        )
        return bool(result.get("success"))
    except Exception as exc:
        logger.warning("Could not enable auto-merge: %s", exc)
        return False
