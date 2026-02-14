"""GitHub-based change control with API caching and rate limiting.

This module implements the primary change control method using GitHub Issues
and Draft Pull Requests, with comprehensive API caching to avoid rate limits.

REFACTORED: Now uses unified utils.cache and utils.github modules instead of
duplicate implementations. Maintains backward compatibility.
"""

import json
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import ChangeController, OptimizationResult

# Import from unified utils modules instead of duplicating
from ...utils.cache import CacheBackend, CacheEntry, GitHubCache
from ...utils.github import RateLimiter

# Issue deprecation warning for direct class usage
warnings.warn(
    "Direct use of GitHubAPICache and AdaptiveRateLimiter from github_control "
    "is deprecated. Use GitHubCache from utils.cache and RateLimiter from "
    "utils.github instead.",
    DeprecationWarning,
    stacklevel=2
)


# Backward compatibility aliases - use utils modules instead
GitHubAPICache = GitHubCache
AdaptiveRateLimiter = RateLimiter


class IssueManager:
    """Manages GitHub issues for optimization tracking.
    
    Creates and updates issues for optimization tasks with:
    - Detailed analysis and rationale
    - Links to related PRs
    - Status tracking
    - Labels for categorization
    """
    
    def __init__(self, api_cache: GitHubAPICache, github_client: Any):
        """Initialize issue manager.
        
        Args:
            api_cache: GitHub API cache instance
            github_client: GitHub API client (e.g., PyGithub)
        """
        self.api_cache = api_cache
        self.github_client = github_client
        
    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new issue.
        
        Args:
            repo: Repository in format "owner/repo"
            title: Issue title
            body: Issue body (markdown)
            labels: Optional list of labels
            
        Returns:
            Created issue data
        """
        # In practice, use github_client.create_issue()
        # For now, return mock data
        issue_data = {
            'number': 123,
            'title': title,
            'body': body,
            'labels': labels or [],
            'html_url': f"https://github.com/{repo}/issues/123",
        }
        
        # Cache the issue
        cache_key = f"issues/{repo}/123"
        self.api_cache.set(cache_key, issue_data)
        
        return issue_data
    
    def get_issue(self, repo: str, issue_number: int) -> Optional[Dict[str, Any]]:
        """Get issue data.
        
        Args:
            repo: Repository in format "owner/repo"
            issue_number: Issue number
            
        Returns:
            Issue data if found, None otherwise
        """
        cache_key = f"issues/{repo}/{issue_number}"
        cached = self.api_cache.get(cache_key)
        
        if cached:
            return cached[0]  # Return value, ignore etag
        
        # Fetch from API and cache
        # In practice: issue_data = github_client.get_issue(repo, issue_number)
        return None
    
    def update_issue(
        self,
        repo: str,
        issue_number: int,
        state: Optional[str] = None,
        labels: Optional[List[str]] = None,
        body: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing issue.
        
        Args:
            repo: Repository in format "owner/repo"
            issue_number: Issue number
            state: Optional new state ("open" or "closed")
            labels: Optional new labels list
            body: Optional new body content
            
        Returns:
            Updated issue data
        """
        # Invalidate cache
        cache_key = f"issues/{repo}/{issue_number}"
        self.api_cache.invalidate(cache_key)
        
        # In practice: updated = github_client.update_issue(...)
        updated = {'number': issue_number, 'state': state}
        
        # Cache updated data
        self.api_cache.set(cache_key, updated)
        
        return updated


class DraftPRManager:
    """Manages draft pull requests for optimization changes.
    
    Creates draft PRs with:
    - Detailed change description
    - Validation results
    - Performance metrics
    - Request for review
    """
    
    def __init__(self, api_cache: GitHubAPICache, github_client: Any):
        """Initialize draft PR manager.
        
        Args:
            api_cache: GitHub API cache instance
            github_client: GitHub API client
        """
        self.api_cache = api_cache
        self.github_client = github_client
        
    def create_draft_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> Dict[str, Any]:
        """Create a draft pull request.
        
        Args:
            repo: Repository in format "owner/repo"
            title: PR title
            body: PR body (markdown)
            head: Head branch name
            base: Base branch name (default: main)
            
        Returns:
            Created PR data
        """
        # In practice: pr = github_client.create_pull(draft=True, ...)
        pr_data = {
            'number': 456,
            'title': title,
            'body': body,
            'head': head,
            'base': base,
            'draft': True,
            'html_url': f"https://github.com/{repo}/pull/456",
        }
        
        # Cache the PR
        cache_key = f"pulls/{repo}/456"
        self.api_cache.set(cache_key, pr_data)
        
        return pr_data
    
    def mark_ready_for_review(self, repo: str, pr_number: int) -> Dict[str, Any]:
        """Mark draft PR as ready for review.
        
        Args:
            repo: Repository in format "owner/repo"
            pr_number: PR number
            
        Returns:
            Updated PR data
        """
        # Invalidate cache
        cache_key = f"pulls/{repo}/{pr_number}"
        self.api_cache.invalidate(cache_key)
        
        # In practice: github_client.mark_ready_for_review(pr_number)
        updated = {'number': pr_number, 'draft': False}
        
        self.api_cache.set(cache_key, updated)
        return updated
    
    def get_pr_status(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        """Get PR status including checks and reviews.
        
        Args:
            repo: Repository in format "owner/repo"
            pr_number: PR number
            
        Returns:
            PR status data if found, None otherwise
        """
        cache_key = f"pulls/{repo}/{pr_number}/status"
        cached = self.api_cache.get(cache_key)
        
        if cached:
            return cached[0]
        
        # In practice: fetch from API
        # status = github_client.get_pr_status(pr_number)
        return None


class GitHubChangeController(ChangeController):
    """Change controller using GitHub Issues and Draft PRs.
    
    This implementation uses GitHub's API with comprehensive caching
    to manage code changes while respecting rate limits.
    """
    
    def __init__(
        self,
        github_client: Any,
        repo: str,
        cache_backend: CacheBackend = CacheBackend.FILE,
        cache_dir: Optional[Path] = None,
        rate_limit_threshold: int = 100,
    ):
        """Initialize GitHub change controller.
        
        Args:
            github_client: GitHub API client
            repo: Repository in format "owner/repo"
            cache_backend: Cache backend to use
            cache_dir: Directory for file-based cache
            rate_limit_threshold: Minimum remaining requests before fallback
        """
        self.github_client = github_client
        self.repo = repo
        self.api_cache = GitHubAPICache(cache_backend, cache_dir)
        self.rate_limiter = AdaptiveRateLimiter(rate_limit_threshold)
        self.issue_manager = IssueManager(self.api_cache, github_client)
        self.pr_manager = DraftPRManager(self.api_cache, github_client)
        self.pending_changes: Dict[str, Dict[str, Any]] = {}
        
    def create_change(self, result: OptimizationResult) -> str:
        """Create change using GitHub issue + draft PR.
        
        Args:
            result: Optimization result to create change for
            
        Returns:
            PR URL
            
        Raises:
            RuntimeError: If rate limit exceeded
        """
        if not self.rate_limiter.can_make_request():
            raise RuntimeError(
                "GitHub API rate limit approaching. Use patch-based fallback."
            )
        
        # Create issue for tracking
        issue_title = f"[Optimization] {result.task_id}: {result.changes[:50]}"
        issue_body = self._format_issue_body(result)
        
        issue = self.issue_manager.create_issue(
            repo=self.repo,
            title=issue_title,
            body=issue_body,
            labels=['optimization', result.method.value],
        )
        
        # Create draft PR
        pr_title = f"Optimization: {result.changes[:50]}"
        pr_body = self._format_pr_body(result, issue['number'])
        branch_name = f"optimization/{result.task_id}"
        
        pr = self.pr_manager.create_draft_pr(
            repo=self.repo,
            title=pr_title,
            body=pr_body,
            head=branch_name,
        )
        
        # Track pending change
        self.pending_changes[pr['html_url']] = {
            'issue': issue,
            'pr': pr,
            'result': result,
        }
        
        return pr['html_url']
    
    def check_approval(self, change_id: str) -> bool:
        """Check if PR has been approved.
        
        Args:
            change_id: PR URL
            
        Returns:
            True if approved, False otherwise
        """
        if not self.rate_limiter.can_make_request():
            # Can't check, assume not approved
            return False
        
        # Extract PR number from URL
        pr_number = int(change_id.split('/')[-1])
        
        # Get PR status
        status = self.pr_manager.get_pr_status(self.repo, pr_number)
        
        if not status:
            return False
        
        # Check for approvals
        return status.get('approved', False)
    
    def apply_change(self, change_id: str) -> bool:
        """Apply approved PR (merge it).
        
        Args:
            change_id: PR URL
            
        Returns:
            True if successfully merged, False otherwise
        """
        if not self.rate_limiter.can_make_request():
            return False
        
        # In practice: github_client.merge_pull_request(pr_number)
        # For now, just remove from pending
        if change_id in self.pending_changes:
            del self.pending_changes[change_id]
        
        return True
    
    def rollback_change(self, change_id: str) -> bool:
        """Rollback a merged PR (create reversal PR).
        
        Args:
            change_id: PR URL to rollback
            
        Returns:
            True if successfully created reversal PR, False otherwise
        """
        # In practice: create a revert PR using GitHub API
        # github_client.create_revert_pull_request(pr_number)
        return True
    
    def _format_issue_body(self, result: OptimizationResult) -> str:
        """Format issue body with optimization details."""
        return f"""## Optimization Task

**Task ID:** `{result.task_id}`
**Method:** {result.method.value}
**Agent:** {result.agent_id}

### Changes
{result.changes}

### Validation Results
- **Success:** {result.validation.passed if result.validation else 'N/A'}
- **Syntax:** {'✓' if result.validation and result.validation.syntax_check else '✗'}
- **Types:** {'✓' if result.validation and result.validation.type_check else '✗'}
- **Tests:** {'✓' if result.validation and result.validation.unit_tests else '✗'}
- **Security:** {'✓' if result.validation and result.validation.security_scan else '✗'}

### Performance Metrics
{self._format_metrics(result.metrics)}

### Execution Time
{result.execution_time:.2f} seconds

---
*Generated by Agentic Optimizer*
"""
    
    def _format_pr_body(self, result: OptimizationResult, issue_number: int) -> str:
        """Format PR body with optimization details."""
        return f"""## Optimization Changes

Closes #{issue_number}

### Summary
{result.changes}

### Method
{result.method.value}

### Validation
- [{'x' if result.validation and result.validation.syntax_check else ' '}] Syntax check passed
- [{'x' if result.validation and result.validation.type_check else ' '}] Type check passed
- [{'x' if result.validation and result.validation.unit_tests else ' '}] Unit tests passed
- [{'x' if result.validation and result.validation.integration_tests else ' '}] Integration tests passed
- [{'x' if result.validation and result.validation.performance_tests else ' '}] Performance tests passed
- [{'x' if result.validation and result.validation.security_scan else ' '}] Security scan passed
- [{'x' if result.validation and result.validation.style_check else ' '}] Style check passed

### Performance Impact
{self._format_metrics(result.metrics)}

---
**Please review and approve if changes look good.**

/cc @reviewers
"""
    
    def _format_metrics(self, metrics: Dict[str, float]) -> str:
        """Format performance metrics."""
        if not metrics:
            return "*No metrics available*"
        
        lines = []
        for key, value in metrics.items():
            lines.append(f"- **{key}:** {value}")
        
        return '\n'.join(lines)
