#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub CLI MCP Server Tools

This module provides MCP server tool functions for GitHub CLI integration.
These functions are designed to be registered with the MCP server for AI assistant access.
"""

from typing import Dict, Any, List, Optional
import logging
from ipfs_datasets_py.utils.github_cli import GitHubCLI

logger = logging.getLogger(__name__)


def github_cli_status(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Get GitHub CLI installation status and information.
    
    Returns information about the GitHub CLI installation including version,
    installation path, platform, architecture, and authentication status.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing status information
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        status = cli.get_status()
        
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        logger.error(f"Failed to get GitHub CLI status: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_install(
    install_dir: Optional[str] = None,
    force: bool = False,
    version: Optional[str] = None
) -> Dict[str, Any]:
    """
    Install or update GitHub CLI.
    
    Downloads and installs the GitHub CLI for the current platform and architecture.
    
    Args:
        install_dir: Optional custom installation directory path
        force: Force reinstallation even if already installed
        version: Optional specific GitHub CLI version to install (e.g., 'v2.40.0')
    
    Returns:
        Dictionary with installation result
    """
    try:
        cli = GitHubCLI(install_dir=install_dir, version=version)
        success = cli.download_and_install(force=force)
        
        if success:
            status = cli.get_status()
            return {
                "success": True,
                "message": "GitHub CLI installed successfully",
                "status": status
            }
        else:
            return {
                "success": False,
                "error": "Installation failed"
            }
    except Exception as e:
        logger.error(f"Failed to install GitHub CLI: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_execute(
    command: List[str],
    install_dir: Optional[str] = None,
    timeout: int = 60
) -> Dict[str, Any]:
    """
    Execute a GitHub CLI command.
    
    Args:
        command: List of command arguments to pass to GitHub CLI
        install_dir: Optional custom installation directory path
        timeout: Command timeout in seconds (default: 60)
    
    Returns:
        Dictionary with command execution results
    """
    try:
        if not isinstance(command, list):
            return {
                "success": False,
                "error": "command must be a list of strings"
            }
        
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.execute(command, timeout=timeout)
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command
        }
    except Exception as e:
        logger.error(f"Failed to execute GitHub CLI command: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_auth_login(
    hostname: str = "github.com",
    web: bool = True,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Authenticate with GitHub.
    
    Args:
        hostname: GitHub hostname (default: github.com, can use GitHub Enterprise)
        web: Use web browser for authentication (default: True)
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with authentication result
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.auth_login(hostname=hostname, web=web)
        
        return {
            "success": result.returncode == 0,
            "hostname": hostname,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        logger.error(f"Failed to authenticate with GitHub: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_auth_status(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Check GitHub authentication status.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with authentication status
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.auth_status()
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        logger.error(f"Failed to get GitHub auth status: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_repo_list(
    limit: int = 30,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    List user's GitHub repositories.
    
    Args:
        limit: Maximum number of repositories to list (default: 30)
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with repository list
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        repos = cli.repo_list(limit=limit)
        
        return {
            "success": True,
            "repositories": repos,
            "count": len(repos)
        }
    except Exception as e:
        logger.error(f"Failed to list GitHub repositories: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_get_repo_info(
    owner: str,
    repo: str,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get detailed information about a GitHub repository.
    
    Fetches repository metadata including description, stars, forks, issues, etc.
    Useful for analyzing repositories before storing in IPFS or generating embeddings.
    
    Args:
        owner: Repository owner (username or organization)
        repo: Repository name
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with repository information
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.execute(['repo', 'view', f'{owner}/{repo}', '--json', 
                             'name,description,url,stars,forks,issues,pullRequests,createdAt,updatedAt,languages'])
        
        if result.returncode == 0:
            import json
            repo_data = json.loads(result.stdout)
            return {
                "success": True,
                "repository": repo_data
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to get repository info: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_get_repo_issues(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 30,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get issues from a GitHub repository.
    
    Fetches issue data that can be stored in IPFS, used for RAG systems,
    or analyzed for project insights.
    
    Args:
        owner: Repository owner (username or organization)
        repo: Repository name
        state: Issue state - "open", "closed", or "all" (default: "open")
        limit: Maximum number of issues to fetch (default: 30)
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with issue list and metadata
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.execute(['issue', 'list', '--repo', f'{owner}/{repo}', 
                             '--state', state, '--limit', str(limit), '--json',
                             'number,title,body,state,createdAt,updatedAt,author,labels'])
        
        if result.returncode == 0:
            import json
            issues = json.loads(result.stdout)
            return {
                "success": True,
                "issues": issues,
                "count": len(issues),
                "repository": f"{owner}/{repo}",
                "state_filter": state
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to get repository issues: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_get_pull_requests(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 30,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get pull requests from a GitHub repository.
    
    Fetches PR data including code changes that can be analyzed,
    stored in IPFS, or used for code review automation.
    
    Args:
        owner: Repository owner (username or organization)
        repo: Repository name
        state: PR state - "open", "closed", "merged", or "all" (default: "open")
        limit: Maximum number of PRs to fetch (default: 30)
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with PR list and metadata
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.execute(['pr', 'list', '--repo', f'{owner}/{repo}', 
                             '--state', state, '--limit', str(limit), '--json',
                             'number,title,body,state,createdAt,updatedAt,author,labels,reviews'])
        
        if result.returncode == 0:
            import json
            prs = json.loads(result.stdout)
            return {
                "success": True,
                "pull_requests": prs,
                "count": len(prs),
                "repository": f"{owner}/{repo}",
                "state_filter": state
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to get pull requests: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_search_repos(
    query: str,
    limit: int = 30,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search GitHub repositories.
    
    Search for repositories matching criteria. Useful for discovering
    datasets, finding similar projects, or building knowledge graphs.
    
    Args:
        query: Search query (e.g., "machine learning python", "topic:nlp", "language:rust")
        limit: Maximum number of results (default: 30)
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with search results
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.execute(['search', 'repos', query, '--limit', str(limit), '--json',
                             'name,fullName,description,url,stars,language,createdAt,updatedAt'])
        
        if result.returncode == 0:
            import json
            repos = json.loads(result.stdout)
            return {
                "success": True,
                "repositories": repos,
                "count": len(repos),
                "query": query
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to search repositories: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_get_user_info(
    username: str,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get information about a GitHub user.
    
    Fetches user profile data useful for building developer knowledge graphs
    or analyzing open source contributions.
    
    Args:
        username: GitHub username
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with user information
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.execute(['api', f'users/{username}'])
        
        if result.returncode == 0:
            import json
            user_data = json.loads(result.stdout)
            return {
                "success": True,
                "user": user_data
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to get user info: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an issue in a GitHub repository.
    
    Useful for automated issue creation, bug reporting from analysis results,
    or tracking tasks discovered during data processing.
    
    Args:
        owner: Repository owner (username or organization)
        repo: Repository name
        title: Issue title
        body: Issue description/body
        labels: Optional list of label names to apply
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with created issue information
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        cmd = ['issue', 'create', '--repo', f'{owner}/{repo}', 
               '--title', title, '--body', body]
        
        if labels:
            cmd.extend(['--label', ','.join(labels)])
        
        result = cli.execute(cmd)
        
        if result.returncode == 0:
            return {
                "success": True,
                "message": "Issue created successfully",
                "output": result.stdout
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to create issue: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_create_pull_request(
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
    draft: bool = False,
    labels: Optional[List[str]] = None,
    reviewers: Optional[List[str]] = None,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a pull request in a GitHub repository.
    
    Creates a new pull request from a head branch to a base branch.
    Useful for automated PR creation from code analysis, refactoring,
    or feature development workflows with AI agents.
    
    Args:
        owner: Repository owner (username or organization)
        repo: Repository name
        title: Pull request title
        body: Pull request description/body
        head: The name of the branch where your changes are implemented
        base: The name of the branch you want to merge into (default: "main")
        draft: Create as a draft PR (default: False)
        labels: Optional list of label names to apply
        reviewers: Optional list of GitHub usernames to request reviews from
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with created PR information including PR number and URL
        
    Example:
        >>> result = github_create_pull_request(
        ...     owner="myorg",
        ...     repo="myrepo",
        ...     title="Add new feature",
        ...     body="This PR adds exciting new functionality",
        ...     head="feature/new-feature",
        ...     base="main",
        ...     labels=["enhancement"],
        ...     reviewers=["reviewer1", "reviewer2"]
        ... )
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        # Build PR creation command
        cmd = [
            'pr', 'create',
            '--repo', f'{owner}/{repo}',
            '--title', title,
            '--body', body,
            '--head', head,
            '--base', base
        ]
        
        if draft:
            cmd.append('--draft')
        
        if labels:
            cmd.extend(['--label', ','.join(labels)])
        
        if reviewers:
            cmd.extend(['--reviewer', ','.join(reviewers)])
        
        result = cli.execute(cmd)
        
        if result.returncode == 0:
            # Parse PR URL from output
            pr_url = result.stdout.strip().split('\n')[-1] if result.stdout else ""
            
            return {
                "success": True,
                "message": "Pull request created successfully",
                "pr_url": pr_url,
                "output": result.stdout
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to create pull request: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_update_pull_request(
    owner: str,
    repo: str,
    pr_number: int,
    title: Optional[str] = None,
    body: Optional[str] = None,
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
    add_reviewers: Optional[List[str]] = None,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update an existing pull request in a GitHub repository.
    
    Allows modification of PR metadata including title, body, labels, and reviewers.
    Useful for AI agents to iteratively refine PRs based on feedback.
    
    Args:
        owner: Repository owner (username or organization)
        repo: Repository name
        pr_number: Pull request number
        title: New PR title (optional)
        body: New PR description/body (optional)
        add_labels: Labels to add (optional)
        remove_labels: Labels to remove (optional)
        add_reviewers: Reviewers to add (optional)
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with update result
        
    Example:
        >>> result = github_update_pull_request(
        ...     owner="myorg",
        ...     repo="myrepo",
        ...     pr_number=123,
        ...     title="Updated: Add new feature",
        ...     add_labels=["ready-for-review"],
        ...     add_reviewers=["newreviewer"]
        ... )
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        # Build PR edit command
        cmd = ['pr', 'edit', str(pr_number), '--repo', f'{owner}/{repo}']
        
        if title:
            cmd.extend(['--title', title])
        
        if body:
            cmd.extend(['--body', body])
        
        if add_labels:
            cmd.extend(['--add-label', ','.join(add_labels)])
        
        if remove_labels:
            cmd.extend(['--remove-label', ','.join(remove_labels)])
        
        if add_reviewers:
            cmd.extend(['--add-reviewer', ','.join(add_reviewers)])
        
        result = cli.execute(cmd)
        
        if result.returncode == 0:
            return {
                "success": True,
                "message": "Pull request updated successfully",
                "output": result.stdout
            }
        else:
            return {
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to update pull request: {e}")
        return {
            "success": False,
            "error": str(e)
        }
