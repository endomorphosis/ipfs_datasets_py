"""Tests for enterprise_api.py - AuthenticationManager, RateLimiter, ProcessingJobManager, AdvancedAnalyticsDashboard."""

import pytest
import sys
import time
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, Any


# ---------------------------------------------------------------------------
# Mock heavy dependencies before importing enterprise_api
# ---------------------------------------------------------------------------

def _setup_mocks():
    """Set up mock modules for enterprise_api imports."""
    mock_graphrag = MagicMock()
    mock_graphrag.CompleteGraphRAGSystem = MagicMock()
    mock_graphrag.CompleteProcessingConfiguration = MagicMock()
    mock_graphrag.CompleteProcessingResult = MagicMock()

    sys.modules.setdefault(
        "ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag",
        mock_graphrag,
    )
    # Also satisfy intermediate package imports
    sys.modules.setdefault("ipfs_datasets_py.processors", MagicMock())
    sys.modules.setdefault("ipfs_datasets_py.processors.graphrag", MagicMock())


_setup_mocks()

# Now import the module under test
from ipfs_datasets_py.mcp_server.enterprise_api import (
    AuthenticationManager,
    RateLimiter,
    ProcessingJobManager,
    WebsiteProcessingRequest,
    AdvancedAnalyticsDashboard,
)


# ---------------------------------------------------------------------------
# AuthenticationManager
# ---------------------------------------------------------------------------

class TestAuthenticationManager:
    """Tests for JWT authentication manager."""

    def setup_method(self):
        """Create a fresh AuthenticationManager with a fixed secret for reproducibility."""
        self.auth = AuthenticationManager(secret_key="test-secret-key")

    def test_create_access_token_returns_string(self):
        """
        GIVEN: A valid username
        WHEN: create_access_token() is called
        THEN: Returns a non-empty string token
        """
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.encode.return_value = "mocked.jwt.token"
            token = self.auth.create_access_token("demo")
            assert isinstance(token, str)
            assert len(token) > 0
            mock_jwt.encode.assert_called_once()

    def test_verify_token_returns_user_data_for_valid_token(self):
        """
        GIVEN: A valid JWT token for an existing user
        WHEN: verify_token() is called
        THEN: Returns user data dict with expected keys
        """
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.decode.return_value = {"sub": "demo"}
            mock_jwt.PyJWTError = Exception  # mock exception class
            result = self.auth.verify_token("valid.token.here")
            assert result is not None
            assert isinstance(result, dict)
            assert "username" in result
            assert result["username"] == "demo"
            assert "roles" in result

    def test_verify_token_returns_none_for_unknown_user(self):
        """
        GIVEN: A valid JWT but for a user not in users_db
        WHEN: verify_token() is called
        THEN: Returns None
        """
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.decode.return_value = {"sub": "nonexistent_user"}
            mock_jwt.PyJWTError = Exception
            result = self.auth.verify_token("some.token")
            assert result is None

    def test_verify_token_returns_none_for_invalid_token(self):
        """
        GIVEN: An invalid JWT token that raises PyJWTError on decode
        WHEN: verify_token() is called
        THEN: Returns None (does not raise)
        """
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            class FakePyJWTError(Exception):
                pass
            mock_jwt.PyJWTError = FakePyJWTError
            mock_jwt.decode.side_effect = FakePyJWTError("invalid token")
            result = self.auth.verify_token("bad.token.value")
            assert result is None

    def test_users_db_contains_demo_and_admin(self):
        """
        GIVEN: A newly created AuthenticationManager
        WHEN: Checking users_db
        THEN: Contains both 'demo' and 'admin' users with expected attributes
        """
        assert "demo" in self.auth.users_db
        assert "admin" in self.auth.users_db
        assert "admin" in self.auth.users_db["admin"].roles
        assert "user" in self.auth.users_db["demo"].roles


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    """Tests for API rate limiting."""

    def setup_method(self):
        self.limiter = RateLimiter()

    def test_first_request_is_allowed(self):
        """
        GIVEN: An empty rate limiter
        WHEN: A user makes their first request to a known endpoint
        THEN: No exception is raised
        """
        asyncio.run(self.limiter.check_limits("user1", "search"))

    def test_unknown_endpoint_always_allowed(self):
        """
        GIVEN: An endpoint with no defined limits
        WHEN: check_limits() is called
        THEN: No exception is raised (even for many calls)
        """
        for _ in range(200):
            asyncio.run(self.limiter.check_limits("user1", "unknown_endpoint"))

    def test_exceeding_rate_limit_raises(self):
        """
        GIVEN: A rate limiter with website_processing limit of 5 per hour
        WHEN: A user makes 6 requests within the window
        THEN: HTTPException is raised on the 6th request
        """
        from fastapi import HTTPException
        # Flood the limiter with exactly the max allowed (5)
        for i in range(5):
            asyncio.run(self.limiter.check_limits("user1", "website_processing"))
        # The 6th should exceed the limit
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(self.limiter.check_limits("user1", "website_processing"))
        assert exc_info.value.status_code == 429

    def test_different_users_have_independent_limits(self):
        """
        GIVEN: Two users, both hitting the website_processing endpoint
        WHEN: One user exceeds their limit
        THEN: The other user is not affected
        """
        from fastapi import HTTPException
        # Flood user1's limit
        for _ in range(5):
            asyncio.run(self.limiter.check_limits("user1", "website_processing"))
        with pytest.raises(HTTPException):
            asyncio.run(self.limiter.check_limits("user1", "website_processing"))
        # user2 should still work fine
        asyncio.run(self.limiter.check_limits("user2", "website_processing"))

    def test_search_endpoint_has_higher_limit_than_processing(self):
        """
        GIVEN: A rate limiter
        WHEN: Checking configured limits
        THEN: 'search' allows 100 requests, 'website_processing' allows only 5
        """
        assert self.limiter.limits["search"]["requests"] > self.limiter.limits["website_processing"]["requests"]


# ---------------------------------------------------------------------------
# ProcessingJobManager
# ---------------------------------------------------------------------------

class TestProcessingJobManager:
    """Tests for job submission and status tracking."""

    def setup_method(self):
        self.manager = ProcessingJobManager()

    def _make_request(self, url: str = "https://example.com") -> WebsiteProcessingRequest:
        return WebsiteProcessingRequest(url=url)

    def test_submit_job_returns_job_id(self):
        """
        GIVEN: A job manager and a valid request
        WHEN: submit_job() is called
        THEN: Returns a non-empty job ID string
        """
        request = self._make_request()
        job_id = asyncio.run(self.manager.submit_job("user1", request))
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    def test_submitted_job_has_queued_status(self):
        """
        GIVEN: A submitted job
        WHEN: get_job_status() is called immediately
        THEN: Status is 'queued'
        """
        request = self._make_request()
        job_id = asyncio.run(self.manager.submit_job("user1", request))
        status = self.manager.get_job_status(job_id)
        assert status is not None
        assert status.status == "queued"

    def test_get_job_status_returns_none_for_unknown_id(self):
        """
        GIVEN: A job manager with no jobs
        WHEN: get_job_status() is called with an unknown job ID
        THEN: Returns None
        """
        result = self.manager.get_job_status("nonexistent-job-id")
        assert result is None

    def test_get_user_jobs_returns_only_user_jobs(self):
        """
        GIVEN: Jobs submitted by two different users
        WHEN: get_user_jobs() is called for user1
        THEN: Only user1's jobs are returned
        """
        r = self._make_request()
        asyncio.run(self.manager.submit_job("user1", r))
        asyncio.run(self.manager.submit_job("user1", r))
        asyncio.run(self.manager.submit_job("user2", r))

        user1_jobs = self.manager.get_user_jobs("user1")
        user2_jobs = self.manager.get_user_jobs("user2")

        assert len(user1_jobs) == 2
        assert len(user2_jobs) == 1

    def test_get_user_jobs_empty_for_unknown_user(self):
        """
        GIVEN: A job manager with no jobs for user99
        WHEN: get_user_jobs('user99') is called
        THEN: Returns empty list
        """
        assert self.manager.get_user_jobs("user99") == []


# ---------------------------------------------------------------------------
# AdvancedAnalyticsDashboard
# ---------------------------------------------------------------------------

class TestAdvancedAnalyticsDashboard:
    """Tests for analytics dashboard."""

    def _make_dashboard_with_jobs(self) -> AdvancedAnalyticsDashboard:
        """Build a dashboard with pre-populated completed/failed jobs."""
        manager = ProcessingJobManager()
        now = datetime.now()

        # Add a completed job
        manager.jobs["j1"] = {
            "job_id": "j1",
            "user_id": "u1",
            "website_url": "https://a.com",
            "status": "completed",
            "progress": 1.0,
            "created_at": now,
            "started_at": now,
            "completed_at": now,
            "error_message": None,
        }
        # Add a failed job
        manager.jobs["j2"] = {
            "job_id": "j2",
            "user_id": "u1",
            "website_url": "https://b.com",
            "status": "failed",
            "progress": 0.3,
            "created_at": now,
            "started_at": now,
            "completed_at": now,
            "error_message": "Connection refused",
        }
        # Add a queued job
        manager.jobs["j3"] = {
            "job_id": "j3",
            "user_id": "u2",
            "website_url": "https://c.com",
            "status": "queued",
            "progress": 0.0,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "error_message": None,
        }
        return AdvancedAnalyticsDashboard(manager)

    def test_generate_system_report_returns_expected_structure(self):
        """
        GIVEN: An AdvancedAnalyticsDashboard with 3 jobs (1 completed, 1 failed, 1 queued)
        WHEN: generate_system_report() is called
        THEN: Returns dict with system_overview, job_statistics, performance_metrics keys
        """
        dashboard = self._make_dashboard_with_jobs()
        report = dashboard.generate_system_report()

        assert "system_overview" in report
        assert "job_statistics" in report
        assert "performance_metrics" in report

    def test_generate_report_job_statistics_counts_correctly(self):
        """
        GIVEN: 3 jobs (1 completed, 1 failed, 1 queued)
        WHEN: generate_system_report() is called
        THEN: job_statistics contains accurate counts
        """
        dashboard = self._make_dashboard_with_jobs()
        stats = dashboard.generate_system_report()["job_statistics"]

        assert stats["completed"] == 1
        assert stats["failed"] == 1
        assert stats["queued"] == 1
        assert stats["processing"] == 0

    def test_generate_report_total_jobs_is_correct(self):
        """
        GIVEN: 3 jobs total
        WHEN: generate_system_report() is called
        THEN: system_overview.total_jobs is 3
        """
        dashboard = self._make_dashboard_with_jobs()
        overview = dashboard.generate_system_report()["system_overview"]
        assert overview["total_jobs"] == 3

    def test_generate_report_empty_manager(self):
        """
        GIVEN: A dashboard with no jobs
        WHEN: generate_system_report() is called
        THEN: Returns valid structure with zeros (no division-by-zero error)
        """
        manager = ProcessingJobManager()
        dashboard = AdvancedAnalyticsDashboard(manager)
        report = dashboard.generate_system_report()

        assert report["system_overview"]["total_jobs"] == 0
        assert report["system_overview"]["success_rate"] == 0
        assert report["job_statistics"]["completed"] == 0


# ---------------------------------------------------------------------------
# WebsiteProcessingRequest (Pydantic model)
# ---------------------------------------------------------------------------

class TestWebsiteProcessingRequest:
    """Tests for request validation model."""

    def test_url_is_required(self):
        """
        GIVEN: No URL provided
        WHEN: WebsiteProcessingRequest is created
        THEN: ValidationError is raised
        """
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            WebsiteProcessingRequest()  # missing url

    def test_default_processing_mode_is_balanced(self):
        """
        GIVEN: A request with only url provided
        WHEN: Created
        THEN: processing_mode defaults to 'balanced'
        """
        req = WebsiteProcessingRequest(url="https://example.com")
        assert req.processing_mode == "balanced"

    def test_crawl_depth_min_is_one(self):
        """
        GIVEN: A request with crawl_depth=0
        WHEN: Created
        THEN: ValidationError is raised
        """
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            WebsiteProcessingRequest(url="https://example.com", crawl_depth=0)

    def test_crawl_depth_max_is_five(self):
        """
        GIVEN: A request with crawl_depth=6
        WHEN: Created
        THEN: ValidationError is raised
        """
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            WebsiteProcessingRequest(url="https://example.com", crawl_depth=6)
