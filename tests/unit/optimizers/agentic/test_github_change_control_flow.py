"""Integration-style test for GitHubChangeController.

This exercises the create -> approval check -> apply -> rollback flow using
mocked managers/status to avoid network calls.
"""

from unittest.mock import Mock

from ipfs_datasets_py.optimizers.agentic.base import (
    OptimizationMethod,
    OptimizationResult,
    ValidationResult,
)
from ipfs_datasets_py.optimizers.agentic.github_control import GitHubChangeController
from ipfs_datasets_py.utils.cache import CacheBackend


def test_github_change_control_flow_smoke() -> None:
    github_client = Mock()

    controller = GitHubChangeController(
        github_client=github_client,
        repo="owner/repo",
        cache_backend=CacheBackend.MEMORY,
    )

    controller.rate_limiter.can_make_request = Mock(return_value=True)

    controller.issue_manager.create_issue = Mock(
        return_value={
            "number": 1,
            "html_url": "https://github.com/owner/repo/issues/1",
        }
    )
    controller.pr_manager.create_draft_pr = Mock(
        return_value={
            "number": 2,
            "html_url": "https://github.com/owner/repo/pull/2",
        }
    )
    controller.pr_manager.get_pr_status = Mock(return_value={"approved": True})

    result = OptimizationResult(
        task_id="task-1",
        success=True,
        method=OptimizationMethod.TEST_DRIVEN,
        changes="Improve formatting and remove duplication.",
        validation=ValidationResult(passed=True),
        metrics={"speedup": 0.1},
        execution_time=0.01,
        agent_id="agent-1",
    )

    change_id = controller.create_change(result)
    assert change_id == "https://github.com/owner/repo/pull/2"
    assert change_id in controller.pending_changes

    assert controller.check_approval(change_id) is True

    assert controller.apply_change(change_id) is True
    assert change_id not in controller.pending_changes

    assert controller.rollback_change(change_id) is True
