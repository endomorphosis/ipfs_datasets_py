"""
Session 40 — Additional tests for enterprise_api.py to push coverage from 66% toward 80%+.

Covers previously-uncovered code paths:
- EnterpriseGraphRAGAPI.__init__() construction
- EnterpriseGraphRAGAPI.create_jwt_token() / validate_jwt_token()
- AdvancedAnalyticsDashboard._calculate_avg_quality() with and without results
- AdvancedAnalyticsDashboard._get_recent_activity() with >10 jobs
- ProcessingJobManager.get_job_status() for missing job
- ProcessingJobManager.get_user_jobs() for specific user
- create_enterprise_api() singleton factory
- AuthenticationManager.authenticate() success + invalid-token paths
"""
import asyncio
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock heavy dependencies before import
# ---------------------------------------------------------------------------

def _setup_mocks():
    mock_graphrag = MagicMock()
    mock_graphrag.CompleteGraphRAGSystem = MagicMock()
    mock_graphrag.CompleteProcessingConfiguration = MagicMock()
    mock_graphrag.CompleteProcessingResult = MagicMock()
    sys.modules.setdefault(
        "ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag",
        mock_graphrag,
    )
    sys.modules.setdefault("ipfs_datasets_py.processors", MagicMock())
    sys.modules.setdefault("ipfs_datasets_py.processors.graphrag", MagicMock())


_setup_mocks()

from ipfs_datasets_py.mcp_server.enterprise_api import (
    AuthenticationManager,
    AdvancedAnalyticsDashboard,
    EnterpriseGraphRAGAPI,
    ProcessingJobManager,
    RateLimiter,
    WebsiteProcessingRequest,
    create_enterprise_api,
)


# ---------------------------------------------------------------------------
# EnterpriseGraphRAGAPI construction
# ---------------------------------------------------------------------------

class TestEnterpriseGraphRAGAPIInit:

    def test_default_init(self):
        """
        GIVEN: No config
        WHEN: EnterpriseGraphRAGAPI is instantiated
        THEN: Default components are created and app is ready
        """
        api = EnterpriseGraphRAGAPI()
        assert api.config == {}
        assert isinstance(api.auth_manager, AuthenticationManager)
        assert isinstance(api.rate_limiter, RateLimiter)
        assert isinstance(api.job_manager, ProcessingJobManager)
        assert api.app is not None

    def test_custom_config(self):
        """
        GIVEN: A custom config dict
        WHEN: EnterpriseGraphRAGAPI is instantiated
        THEN: config attribute is set correctly
        """
        api = EnterpriseGraphRAGAPI(config={"max_jobs": 50})
        assert api.config["max_jobs"] == 50

    def test_graphrag_systems_cache_starts_empty(self):
        api = EnterpriseGraphRAGAPI()
        assert api.graphrag_systems == {}


# ---------------------------------------------------------------------------
# EnterpriseGraphRAGAPI.create_jwt_token / validate_jwt_token
# ---------------------------------------------------------------------------

class TestEnterpriseGraphRAGAPITokenMethods:

    def setup_method(self):
        self.api = EnterpriseGraphRAGAPI()

    def test_create_jwt_token_with_username(self):
        """create_jwt_token() with username key returns a non-empty token string."""
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.encode.return_value = "mock.token.here"
            token = self.api.create_jwt_token({"username": "demo"})
            assert isinstance(token, str)
            assert len(token) > 0

    def test_create_jwt_token_with_user_id(self):
        """create_jwt_token() falls back to user_id if username not provided."""
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.encode.return_value = "mock.token.here"
            token = self.api.create_jwt_token({"user_id": "usr-42"})
            assert isinstance(token, str)

    def test_validate_jwt_token_valid(self):
        """validate_jwt_token() returns user data dict for a valid token."""
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.decode.return_value = {"sub": "demo"}
            mock_jwt.PyJWTError = Exception
            result = self.api.validate_jwt_token("valid.token")
            assert result is not None
            assert result["username"] == "demo"

    def test_validate_jwt_token_invalid(self):
        """validate_jwt_token() returns None for an invalid token."""
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.decode.side_effect = Exception("invalid")
            mock_jwt.PyJWTError = Exception
            result = self.api.validate_jwt_token("bad.token")
            assert result is None


# ---------------------------------------------------------------------------
# ProcessingJobManager — additional paths
# ---------------------------------------------------------------------------

class TestProcessingJobManagerAdditional:

    def test_get_job_status_missing_job_returns_none(self):
        """get_job_status() returns None for a job_id that doesn't exist."""
        jm = ProcessingJobManager()
        result = jm.get_job_status("nonexistent-id")
        assert result is None

    def test_get_user_jobs_filters_by_user(self):
        """get_user_jobs() returns only jobs belonging to the specified user."""
        jm = ProcessingJobManager()
        req = WebsiteProcessingRequest(url="https://example.com")
        asyncio.run(jm.submit_job("alice", req))
        asyncio.run(jm.submit_job("bob", req))
        alice_jobs = jm.get_user_jobs("alice")
        # Only alice's job should be returned
        assert len(alice_jobs) == 1

    def test_get_user_jobs_empty_for_unknown_user(self):
        jm = ProcessingJobManager()
        assert jm.get_user_jobs("unknown_user") == []


# ---------------------------------------------------------------------------
# AdvancedAnalyticsDashboard — additional paths
# ---------------------------------------------------------------------------

class TestAdvancedAnalyticsDashboardAdditional:

    def _make_dashboard(self):
        jm = ProcessingJobManager()
        return AdvancedAnalyticsDashboard(job_manager=jm)

    def test_calculate_avg_quality_no_results(self):
        """_calculate_avg_quality() returns 0.0 when no job results exist."""
        dashboard = self._make_dashboard()
        result = dashboard._calculate_avg_quality()
        assert result == 0.0

    def test_calculate_avg_quality_with_results(self):
        """_calculate_avg_quality() returns average quality_score across results."""
        dashboard = self._make_dashboard()
        # Add mock results with quality_score attribute
        mock_result_a = MagicMock()
        mock_result_a.quality_score = 0.8
        mock_result_b = MagicMock()
        mock_result_b.quality_score = 0.6
        dashboard.job_manager.job_results["job-a"] = mock_result_a
        dashboard.job_manager.job_results["job-b"] = mock_result_b
        result = dashboard._calculate_avg_quality()
        assert result == pytest.approx(0.7)

    def test_get_recent_activity_returns_list(self):
        """_get_recent_activity() returns a list of dicts."""
        dashboard = self._make_dashboard()
        # Add a single job manually
        dashboard.job_manager.jobs["j1"] = {
            "job_id": "j1",
            "website_url": "https://example.com",
            "status": "completed",
            "created_at": datetime.now(),
            "processing_mode": "fast",
        }
        activity = dashboard._get_recent_activity()
        assert isinstance(activity, list)
        assert len(activity) == 1
        assert activity[0]["job_id"] == "j1"

    def test_get_recent_activity_capped_at_10(self):
        """_get_recent_activity() returns at most 10 items even with >10 jobs."""
        dashboard = self._make_dashboard()
        for i in range(15):
            dashboard.job_manager.jobs[f"job-{i}"] = {
                "job_id": f"job-{i}",
                "website_url": f"https://example{i}.com",
                "status": "completed",
                "created_at": datetime.now(),
                "processing_mode": "fast",
            }
        activity = dashboard._get_recent_activity()
        assert len(activity) <= 10

    def test_generate_system_report_structure(self):
        """generate_system_report() returns dict with expected top-level keys."""
        dashboard = self._make_dashboard()
        report = dashboard.generate_system_report()
        assert "system_overview" in report
        assert "job_statistics" in report
        assert "performance_metrics" in report
        assert "recent_activity" in report


# ---------------------------------------------------------------------------
# create_enterprise_api() factory
# ---------------------------------------------------------------------------

class TestCreateEnterpriseAPIFactory:

    def test_create_enterprise_api_returns_instance(self):
        """create_enterprise_api() returns an EnterpriseGraphRAGAPI instance."""
        import ipfs_datasets_py.mcp_server.enterprise_api as _mod
        original = _mod.api_instance
        try:
            _mod.api_instance = None
            api = asyncio.run(create_enterprise_api())
            assert isinstance(api, EnterpriseGraphRAGAPI)
        finally:
            _mod.api_instance = original

    def test_create_enterprise_api_returns_singleton(self):
        """create_enterprise_api() returns the same instance on repeated calls."""
        import ipfs_datasets_py.mcp_server.enterprise_api as _mod
        original = _mod.api_instance
        try:
            _mod.api_instance = None
            api1 = asyncio.run(create_enterprise_api())
            api2 = asyncio.run(create_enterprise_api())
            assert api1 is api2
        finally:
            _mod.api_instance = original


# ---------------------------------------------------------------------------
# AuthenticationManager.authenticate()
# ---------------------------------------------------------------------------

class TestAuthManagerAuthenticate:

    def test_authenticate_valid_token_returns_user(self):
        """authenticate() returns a User for a valid token with known username."""
        auth = AuthenticationManager(secret_key="test-secret")
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.decode.return_value = {"sub": "demo"}
            mock_jwt.PyJWTError = Exception
            user = asyncio.run(auth.authenticate("valid.token"))
            assert user.username == "demo"
            assert user.is_active

    def test_authenticate_invalid_token_raises_http_exception(self):
        """authenticate() raises HTTPException for an invalid/expired token."""
        from fastapi import HTTPException
        auth = AuthenticationManager(secret_key="test-secret")
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.decode.side_effect = Exception("invalid")
            mock_jwt.PyJWTError = Exception
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(auth.authenticate("bad.token"))
            assert exc_info.value.status_code == 401

    def test_authenticate_unknown_user_raises_http_exception(self):
        """authenticate() raises HTTPException when username not in users_db."""
        from fastapi import HTTPException
        auth = AuthenticationManager(secret_key="test-secret")
        with patch("ipfs_datasets_py.mcp_server.enterprise_api.jwt") as mock_jwt:
            mock_jwt.decode.return_value = {"sub": "unknown_user"}
            mock_jwt.PyJWTError = Exception
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(auth.authenticate("token.for.unknown"))
            assert exc_info.value.status_code == 401
